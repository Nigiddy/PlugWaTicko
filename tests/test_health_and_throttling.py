from django.test import TestCase
from django.conf import settings
from rest_framework.test import APIClient


class HealthAndThrottlingTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_check_endpoint(self):
        response = self.client.get('/health/')
        self.assertIn(response.status_code, [200, 503])
        self.assertIn('status', response.data)
        self.assertIn('services', response.data)
        self.assertIn('database', response.data['services'])

    def test_settings_throttling_configuration(self):
        # Verify base settings define proper throttle rates
        from Event_Project.settings.base import REST_FRAMEWORK
        rates = REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
        self.assertEqual(rates.get('auth_endpoints'), '10/minute')
        self.assertEqual(rates.get('payment_init'), '15/minute')
        self.assertEqual(rates.get('ticket_checkin'), '120/minute')
        self.assertEqual(rates.get('anon'), '60/minute')
        self.assertEqual(rates.get('user'), '300/minute')

    def test_cookie_security_in_production(self):
        from Event_Project.settings import production
        self.assertTrue(production.SESSION_COOKIE_SECURE)
        self.assertTrue(production.CSRF_COOKIE_SECURE)
        self.assertTrue(production.CSRF_COOKIE_HTTPONLY)
        self.assertTrue(production.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(production.REST_AUTH['JWT_AUTH_SECURE'])
        self.assertEqual(production.REST_AUTH['JWT_AUTH_SAMESITE'], 'Lax')

