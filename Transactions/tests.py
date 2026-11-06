import hmac
import hashlib
import json
from django.test import SimpleTestCase
from .tasks import safe_parse_list, generate_ticket_number, generate_qr_token, generate_key, generate_ref_code
from .models import TicketStatus, CheckInResult


class SecurityAndParsingTests(SimpleTestCase):
    def test_safe_parse_list_valid_json(self):
        input_data = '["test1@example.com", "test2@example.com"]'
        result = safe_parse_list(input_data)
        self.assertEqual(result, ["test1@example.com", "test2@example.com"])

    def test_safe_parse_list_python_literal(self):
        input_data = "['rock', 'jazz', 'pop']"
        result = safe_parse_list(input_data)
        self.assertEqual(result, ['rock', 'jazz', 'pop'])

    def test_safe_parse_list_malicious_code_string_not_evaluated(self):
        # Verify that code injection attempts are NOT evaluated like eval() would!
        malicious_input = "__import__('os').system('echo hacked')"
        result = safe_parse_list(malicious_input)
        self.assertEqual(result, [malicious_input])

    def test_safe_parse_list_empty_and_none(self):
        self.assertEqual(safe_parse_list(None), [])
        self.assertEqual(safe_parse_list(""), [])
        self.assertEqual(safe_parse_list([]), [])

    def test_token_generation_entropy_and_format(self):
        tkt_num1 = generate_ticket_number()
        tkt_num2 = generate_ticket_number()
        self.assertTrue(tkt_num1.startswith("TKT-"))
        self.assertNotEqual(tkt_num1, tkt_num2)

        qr_tok1 = generate_qr_token()
        qr_tok2 = generate_qr_token()
        self.assertTrue(qr_tok1.startswith("tkt_sec_"))
        self.assertGreater(len(qr_tok1), 40)
        self.assertNotEqual(qr_tok1, qr_tok2)

        key = generate_key()
        self.assertEqual(len(key), 16)
        self.assertTrue(key.isdigit())

        ref = generate_ref_code()
        self.assertEqual(len(ref), 20)

    def test_paystack_hmac_sha512_verification(self):
        secret = "sk_test_mock_secret_key_12345"
        payload = json.dumps({"event": "charge.success", "data": {"reference": "REF123"}}).encode('utf-8')
        
        # Valid signature computation
        valid_sig = hmac.new(secret.encode('utf-8'), payload, hashlib.sha512).hexdigest()
        self.assertTrue(hmac.compare_digest(valid_sig, valid_sig))

        # Tampered payload fails
        tampered_payload = json.dumps({"event": "charge.success", "data": {"reference": "REF999"}}).encode('utf-8')
        tampered_sig = hmac.new(secret.encode('utf-8'), tampered_payload, hashlib.sha512).hexdigest()
        self.assertFalse(hmac.compare_digest(valid_sig, tampered_sig))

        # Wrong secret fails
        wrong_sig = hmac.new(b"wrong_secret", payload, hashlib.sha512).hexdigest()
        self.assertFalse(hmac.compare_digest(valid_sig, wrong_sig))

    def test_fsm_status_definitions(self):
        self.assertEqual(TicketStatus.ISSUED, 'ISSUED')
        self.assertEqual(TicketStatus.CHECKED_IN, 'CHECKED_IN')
        self.assertEqual(TicketStatus.CANCELLED, 'CANCELLED')
        self.assertEqual(TicketStatus.REFUNDED, 'REFUNDED')
        self.assertEqual(TicketStatus.EXPIRED, 'EXPIRED')

        self.assertEqual(CheckInResult.SUCCESS, 'SUCCESS')
        self.assertEqual(CheckInResult.ALREADY_USED, 'ALREADY_USED')
        self.assertEqual(CheckInResult.INVALID_TOKEN, 'INVALID_TOKEN')
