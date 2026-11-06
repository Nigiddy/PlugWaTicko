from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from Events.models import Event, TicketPrice, OrderTicket
from Transactions.models import Payment, SoldTicket, CheckInLog, TicketStatus, CheckInResult

User = get_user_model()


class CheckInLifecycleTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            email='gatekeeper@example.com',
            password='TestPassword123!',
            first_name='Gate',
            last_name='Staff'
        )
        self.attendee = User.objects.create_user(
            email='attendee@example.com',
            password='TestPassword123!',
            first_name='Jane',
            last_name='Smith'
        )
        self.event = Event.objects.create(
            user=self.staff_user,
            name='Music & Arts Festival 2026',
            country='Nigeria',
            city='Lagos',
            state='Lagos',
            address='Tafawa Balewa Square',
            start_date=timezone.now() + timedelta(days=2),
            end_date=timezone.now() + timedelta(days=3),
            approved=True
        )
        self.tier = TicketPrice.objects.create(
            event=self.event,
            label='General Admission',
            price=10000.0,
            qty=50,
            sold=1
        )
        self.order = OrderTicket.objects.create(
            user=self.attendee,
            event=self.event,
            status='completed'
        )
        self.payment = Payment.objects.create(
            user=self.attendee,
            ticket=self.order,
            payment_id='PAY-TEST-999',
            amount=10000.0
        )
        self.ticket = SoldTicket.objects.create(
            user=self.attendee,
            payment=self.payment,
            event=self.order,
            ticket=self.tier,
            ticket_number='TKT-2026-F1A2B3C4',
            qr_code_token='tkt_sec_mock_test_token_abcdef1234567890',
            key='1234567890123456',
            status=TicketStatus.ISSUED,
            used=False
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.staff_user)

    def test_verify_endpoint_is_read_only(self):
        url = '/api/v1/tickets/verify/'
        response = self.client.post(url, {'token': self.ticket.qr_code_token, 'event_id': str(self.event.id)}, format='json')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['valid'])
        self.assertEqual(response.data['status'], 'ISSUED')
        self.assertEqual(response.data['attendee_name'], 'Jane Smith')

        # Verify state was NOT mutated
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.ISSUED)
        self.assertFalse(self.ticket.used)
        self.assertIsNone(self.ticket.checked_in_at)

    def test_successful_first_time_checkin(self):
        url = '/api/v1/tickets/check-in/'
        response = self.client.post(url, {
            'token': self.ticket.qr_code_token,
            'event_id': str(self.event.id),
            'gate': 'Gate 4 VIP'
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'SUCCESS')
        self.assertEqual(response.data['ticket']['gate'], 'Gate 4 VIP')

        # Verify state mutated in database
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.CHECKED_IN)
        self.assertTrue(self.ticket.used)
        self.assertIsNotNone(self.ticket.checked_in_at)
        self.assertEqual(self.ticket.checked_in_by, self.staff_user)
        self.assertEqual(self.ticket.check_in_gate, 'Gate 4 VIP')

        # Verify CheckInLog entry
        log = CheckInLog.objects.filter(ticket=self.ticket).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.result, CheckInResult.SUCCESS)
        self.assertEqual(log.gate, 'Gate 4 VIP')

    def test_duplicate_scan_rejected_with_409_conflict(self):
        checkin_url = '/api/v1/tickets/check-in/'

        # First scan: Success
        first_resp = self.client.post(checkin_url, {'token': self.ticket.qr_code_token, 'event_id': str(self.event.id), 'gate': 'Gate 1'}, format='json')
        self.assertEqual(first_resp.status_code, 200)

        # Second scan of identical token: Rejection with 409 Conflict
        second_resp = self.client.post(checkin_url, {'token': self.ticket.qr_code_token, 'event_id': str(self.event.id), 'gate': 'Gate 2'}, format='json')
        self.assertEqual(second_resp.status_code, 409)
        self.assertEqual(second_resp.data['status'], 'ALREADY_CHECKED_IN')
        self.assertIn('original_checkin_time', second_resp.data['ticket'])

        # Verify duplicate attempt was logged to audit trail
        logs = CheckInLog.objects.filter(ticket=self.ticket).order_by('-scanned_at')
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs.first().result, CheckInResult.ALREADY_USED)

    def test_cancelled_ticket_rejected(self):
        self.ticket.status = TicketStatus.CANCELLED
        self.ticket.save()

        url = '/api/v1/tickets/check-in/'
        response = self.client.post(url, {'token': self.ticket.qr_code_token, 'event_id': str(self.event.id)}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['status'], 'CANCELLED')

