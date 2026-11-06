import hmac
import hashlib
import json
from django.conf import settings
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from Events.models import Event, TicketPrice, OrderTicket, BuyTicket, OrderStatus
from Transactions.models import Payment
from Transactions.tasks import create_payment_record

User = get_user_model()


class WebhookSecurityAndLatePaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='paytester@example.com',
            password='TestPassword123!',
            first_name='Alex',
            last_name='Pay'
        )
        self.event = Event.objects.create(
            user=self.user,
            name='Global Fintech Forum 2026',
            country='Nigeria',
            city='Lagos',
            state='Lagos',
            address='Victoria Island',
            start_date='2026-12-01T09:00:00Z',
            end_date='2026-12-02T18:00:00Z',
            approved=True
        )
        self.tier = TicketPrice.objects.create(
            event=self.event,
            label='Delegate Pass',
            price=50000.0,
            qty=20,
            sold=0,
            reserved=1
        )
        self.order = OrderTicket.objects.create(
            user=self.user,
            event=self.event,
            status=OrderStatus.RESERVED
        )
        self.buy_ticket = BuyTicket.objects.create(
            user=self.user,
            event_ticket=self.tier,
            order=self.order,
            qty=1,
            completed=False
        )
        self.client = APIClient()

    def _sign_payload(self, body_bytes: bytes) -> str:
        secret = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
        return hmac.new(secret, body_bytes, hashlib.sha512).hexdigest()

    def test_webhook_rejected_when_signature_missing(self):
        payload = json.dumps({'event': 'charge.success', 'data': {}}).encode('utf-8')
        response = self.client.post('/api/v1/paystack-webhook/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Missing signature')

    def test_webhook_rejected_when_signature_invalid(self):
        payload = json.dumps({'event': 'charge.success', 'data': {}}).encode('utf-8')
        response = self.client.post(
            '/api/v1/paystack-webhook/',
            data=payload,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='tampered_invalid_hex_signature'
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Invalid signature')

    def test_webhook_accepted_when_signature_valid(self):
        body = {
            'event': 'charge.success',
            'data': {
                'reference': 'PSTK_REF_001',
                'amount': 5000000,
                'metadata': {
                    'user_id': str(self.user.id),
                    'bought_ticket_id': str(self.order.id),
                    'price': 50000.0,
                    'email': 'paytester@example.com'
                }
            }
        }
        payload = json.dumps(body).encode('utf-8')
        signature = self._sign_payload(payload)

        response = self.client.post(
            '/api/v1/paystack-webhook/',
            data=payload,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        self.assertEqual(response.status_code, 200)

    def test_webhook_idempotency_ignores_already_processed_payment(self):
        # Pre-create payment record with reference PSTK_REF_EXISTING
        Payment.objects.create(
            user=self.user,
            ticket=self.order,
            payment_id='PSTK_REF_EXISTING',
            amount=50000.0
        )

        body = {
            'event': 'charge.success',
            'data': {
                'reference': 'PSTK_REF_EXISTING',
                'metadata': {
                    'bought_ticket_id': str(self.order.id)
                }
            }
        }
        payload = json.dumps(body).encode('utf-8')
        signature = self._sign_payload(payload)

        # Post webhook again
        response = self.client.post(
            '/api/v1/paystack-webhook/',
            data=payload,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        # Must return 200 without raising error or re-processing
        self.assertEqual(response.status_code, 200)

