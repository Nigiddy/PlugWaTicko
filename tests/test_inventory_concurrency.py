from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models
from rest_framework.test import APIClient

from Events.models import Event, TicketPrice, OrderTicket, BuyTicket, OrderStatus
from Transactions.tasks import release_expired_ticket_reservations

User = get_user_model()


class InventoryAndReservationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='buyer@example.com',
            password='TestPassword123!',
            first_name='John',
            last_name='Doe'
        )
        self.organizer = User.objects.create_user(
            email='organizer@example.com',
            password='TestPassword123!',
            first_name='Event',
            last_name='Organizer'
        )
        self.event = Event.objects.create(
            user=self.organizer,
            name='Tech Innovators Summit 2026',
            country='Nigeria',
            city='Lagos',
            state='Lagos',
            address='Eko Convention Centre',
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=6),
            approved=True
        )
        self.ticket_tier = TicketPrice.objects.create(
            event=self.event,
            label='VIP Gold',
            price=25000.0,
            qty=10,
            sold=0,
            reserved=0
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_available_tickets_calculation(self):
        self.assertEqual(self.ticket_tier.get_tickets_available(), 10)

        # Increment reserved
        self.ticket_tier.reserved = 3
        self.ticket_tier.save()
        self.assertEqual(self.ticket_tier.get_tickets_available(), 7)

        # Increment sold
        self.ticket_tier.sold = 5
        self.ticket_tier.save()
        self.assertEqual(self.ticket_tier.get_tickets_available(), 2)

    def test_database_check_constraint_prevents_overselling(self):
        # Database constraint ticketprice_sold_lte_qty must reject sold > qty
        with self.assertRaises(IntegrityError):
            TicketPrice.objects.filter(id=self.ticket_tier.id).update(sold=15)

    def test_database_check_constraint_prevents_sold_plus_reserved_exceeding_qty(self):
        # Database constraint ticketprice_sold_plus_reserved_lte_qty must reject sold + reserved > qty
        with self.assertRaises(IntegrityError):
            TicketPrice.objects.filter(id=self.ticket_tier.id).update(sold=6, reserved=5)

    def test_buy_ticket_view_creates_atomic_reservation_with_ttl(self):
        url = f'/api/v1/buy-ticket/{self.ticket_tier.id}/'
        response = self.client.post(url, {'qty': 2, 'emails': ['test1@example.com', 'test2@example.com']}, format='json')
        
        self.assertEqual(response.status_code, 201)
        self.assertIn('reservation_expires_at', response.data)
        self.assertEqual(response.data['expires_in_seconds'], 900)

        # Check inventory state
        self.ticket_tier.refresh_from_db()
        self.assertEqual(self.ticket_tier.reserved, 2)
        self.assertEqual(self.ticket_tier.get_tickets_available(), 8)

        # Check order state
        order = OrderTicket.objects.get(user=self.user, event=self.event)
        self.assertEqual(order.status, OrderStatus.RESERVED)
        self.assertIsNotNone(order.reservation_expires_at)
        self.assertFalse(order.is_expired())

    def test_remove_ticket_releases_reserved_inventory(self):
        # First reserve 4 tickets
        buy_url = f'/api/v1/buy-ticket/{self.ticket_tier.id}/'
        self.client.post(buy_url, {'qty': 4, 'emails': []}, format='json')
        self.ticket_tier.refresh_from_db()
        self.assertEqual(self.ticket_tier.reserved, 4)

        # Now remove them from cart
        remove_url = f'/api/v1/remove-ticket/{self.ticket_tier.id}'
        response = self.client.post(remove_url)
        self.assertEqual(response.status_code, 204)

        # Check that reserved tickets were released back to availability
        self.ticket_tier.refresh_from_db()
        self.assertEqual(self.ticket_tier.reserved, 0)
        self.assertEqual(self.ticket_tier.get_tickets_available(), 10)

    def test_periodic_worker_releases_expired_reservations(self):
        # Create an order with reservation expired 5 minutes ago
        expired_order = OrderTicket.objects.create(
            user=self.user,
            event=self.event,
            status=OrderStatus.RESERVED,
            reservation_expires_at=timezone.now() - timedelta(minutes=5)
        )
        BuyTicket.objects.create(
            user=self.user,
            event_ticket=self.ticket_tier,
            order=expired_order,
            qty=3,
            completed=False
        )
        self.ticket_tier.reserved = 3
        self.ticket_tier.save()
        self.assertEqual(self.ticket_tier.get_tickets_available(), 7)

        # Run the celery beat task
        release_expired_ticket_reservations()

        # Check that reservation was marked EXPIRED and inventory restored
        expired_order.refresh_from_db()
        self.assertEqual(expired_order.status, OrderStatus.EXPIRED)

        self.ticket_tier.refresh_from_db()
        self.assertEqual(self.ticket_tier.reserved, 0)
        self.assertEqual(self.ticket_tier.get_tickets_available(), 10)

