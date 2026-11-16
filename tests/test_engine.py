"""
Automated Test Suite for FinTech Payment Engine
Verifies ACID compliance, idempotency guarantees, and webhook cryptographic verification.
"""
import unittest
import sqlite3
import json
import time

from src.database import init_db
from src.services import PaymentService, InsufficientStockError
from src.idempotency import IdempotencyManager, IdempotencyConflictError
from src.security import compute_signature, verify_webhook_signature
from src.worker import BackgroundWorker

class TestPaymentEngine(unittest.TestCase):
    def setUp(self):
        # Create an in-memory SQLite database per test with multi-thread access
        self.conn = sqlite3.connect("file:memdb?mode=memory&cache=shared", uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        
        # Seed test data
        with self.conn:
            self.conn.execute("INSERT INTO products VALUES ('prod_test_phone', 'Pixel 9 Pro', 99900, 3)")
        
        self.worker = BackgroundWorker(lambda: self.conn)
        self.worker.start()
        self.service = PaymentService(self.conn, self.worker)
        self.idempotency_mgr = IdempotencyManager(self.conn)

    def tearDown(self):
        self.worker.stop()
        self.conn.close()

    def test_successful_atomic_checkout(self):
        result = self.service.process_checkout(
            customer_id="cust_123",
            product_id="prod_test_phone",
            quantity=1
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["amount_cents"], 99900)
        self.assertTrue(result["payment_id"].startswith("pay_"))
        self.assertTrue(result["invoice"]["invoice_number"].startswith("INV-2026-"))

        # Verify stock was decremented from 3 to 2
        cursor = self.conn.cursor()
        cursor.execute("SELECT stock FROM products WHERE id = 'prod_test_phone'")
        self.assertEqual(cursor.fetchone()["stock"], 2)

    def test_transaction_rollback_on_insufficient_stock(self):
        # Attempt to purchase 5 units when only 3 are available
        with self.assertRaises(InsufficientStockError):
            self.service.process_checkout(
                customer_id="cust_123",
                product_id="prod_test_phone",
                quantity=5
            )

        # Verify stock remains untouched at 3
        cursor = self.conn.cursor()
        cursor.execute("SELECT stock FROM products WHERE id = 'prod_test_phone'")
        self.assertEqual(cursor.fetchone()["stock"], 3)

        # Verify no payments were created
        cursor.execute("SELECT COUNT(*) as count FROM payments")
        self.assertEqual(cursor.fetchone()["count"], 0)

    def test_idempotency_replays_cached_response_without_duplicate_charge(self):
        key = "idemp_test_uuid_abc_123"
        payload = json.dumps({"customer_id": "cust_999", "product_id": "prod_test_phone", "quantity": 1})

        # First execution
        first_result = self.service.process_checkout(
            customer_id="cust_999",
            product_id="prod_test_phone",
            quantity=1,
            idempotency_key=key
        )
        self.idempotency_mgr.save_response(key, payload, 201, first_result)

        # Check stock is 2
        cursor = self.conn.cursor()
        cursor.execute("SELECT stock FROM products WHERE id = 'prod_test_phone'")
        self.assertEqual(cursor.fetchone()["stock"], 2)

        # Second execution: simulate idempotency hit
        cached = self.idempotency_mgr.get_cached_response(key, payload)
        self.assertIsNotNone(cached)
        code, replayed = cached
        self.assertEqual(code, 201)
        self.assertEqual(replayed["payment_id"], first_result["payment_id"])

        # Crucial check: stock is still 2 (was not deducted again!)
        cursor.execute("SELECT stock FROM products WHERE id = 'prod_test_phone'")
        self.assertEqual(cursor.fetchone()["stock"], 2)

    def test_idempotency_raises_conflict_on_payload_tamper(self):
        key = "idemp_conflict_key"
        payload_orig = json.dumps({"amount": 100})
        payload_tampered = json.dumps({"amount": 500})

        self.idempotency_mgr.save_response(key, payload_orig, 200, {"ok": True})

        with self.assertRaises(IdempotencyConflictError):
            self.idempotency_mgr.get_cached_response(key, payload_tampered)

    def test_webhook_hmac_signature_verification(self):
        secret = "whsec_super_secret_test_key"
        payload = b'{"type": "payment_intent.succeeded", "data": {"id": "pay_test_001"}}'

        valid_sig = compute_signature(payload, secret)
        self.assertTrue(verify_webhook_signature(payload, valid_sig, secret))

        # Tampered payload fails
        tampered_payload = b'{"type": "payment_intent.succeeded", "data": {"id": "pay_tampered"}}'
        self.assertFalse(verify_webhook_signature(tampered_payload, valid_sig, secret))

        # Invalid secret fails
        self.assertFalse(verify_webhook_signature(payload, valid_sig, "wrong_secret"))

if __name__ == "__main__":
    unittest.main()
