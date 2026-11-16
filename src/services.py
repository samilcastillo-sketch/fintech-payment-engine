"""
Payment Processing & Core Business Domain Services
Implements atomic transactions (ACID) and stock reservation patterns.
"""
import uuid
import sqlite3
from typing import Dict, Any

class InsufficientStockError(Exception):
    pass

class ProductNotFoundError(Exception):
    pass

class PaymentService:
    def __init__(self, conn: sqlite3.Connection, worker=None):
        self.conn = conn
        self.worker = worker

    def process_checkout(self, customer_id: str, product_id: str, quantity: int, idempotency_key: str = None) -> Dict[str, Any]:
        """
        Executes an atomic checkout:
        1. Checks and locks product stock
        2. Deducts stock
        3. Creates payment transaction
        4. Issues fiscal invoice
        5. Dispatches async worker job
        All wrapped in a single database transaction.
        """
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")

        # Begin transaction
        with self.conn:
            cursor = self.conn.cursor()
            
            # 1. Fetch product
            cursor.execute("SELECT id, name, price_cents, stock FROM products WHERE id = ?", (product_id,))
            product = cursor.fetchone()
            if not product:
                raise ProductNotFoundError(f"Product {product_id} not found.")

            if product["stock"] < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock for {product['name']}. Available: {product['stock']}, Requested: {quantity}"
                )

            # 2. Atomic stock decrement
            cursor.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (quantity, product_id, quantity)
            )
            if cursor.rowcount == 0:
                raise InsufficientStockError("Concurrent stock conflict: stock was depleted.")

            total_amount = product["price_cents"] * quantity
            payment_id = f"pay_{uuid.uuid4().hex[:12]}"
            invoice_id = f"inv_{uuid.uuid4().hex[:12]}"
            invoice_number = f"INV-2026-{uuid.uuid4().hex[:6].upper()}"

            # 3. Create payment record
            cursor.execute(
                """
                INSERT INTO payments (id, customer_id, amount_cents, currency, status, idempotency_key)
                VALUES (?, ?, ?, 'USD', 'succeeded', ?)
                """,
                (payment_id, customer_id, total_amount, idempotency_key)
            )

            # 4. Generate invoice
            cursor.execute(
                """
                INSERT INTO invoices (id, payment_id, invoice_number, amount_cents, pdf_generated)
                VALUES (?, ?, ?, ?, 0)
                """,
                (invoice_id, payment_id, invoice_number, total_amount)
            )

        # 5. Enqueue background jobs outside the lock
        if self.worker:
            self.worker.enqueue_job("GENERATE_INVOICE_PDF", {"invoice_id": invoice_id})
            self.worker.enqueue_job("AUDIT_EVENT", {
                "event_type": "PAYMENT_SUCCEEDED",
                "payload": f"Payment {payment_id} for amount {total_amount} succeeded."
            })

        return {
            "payment_id": payment_id,
            "status": "succeeded",
            "amount_cents": total_amount,
            "currency": "USD",
            "invoice": {
                "id": invoice_id,
                "invoice_number": invoice_number,
                "pdf_status": "queued"
            }
        }

    def handle_stripe_webhook_event(self, event_type: str, event_data: dict) -> dict:
        """Processes verified incoming webhook events from Stripe."""
        with self.conn:
            cursor = self.conn.cursor()
            if event_type == "payment_intent.succeeded":
                intent_id = event_data.get("id")
                cursor.execute(
                    "UPDATE payments SET status = 'succeeded' WHERE id = ?",
                    (intent_id,)
                )
            elif event_type == "charge.refunded":
                charge_id = event_data.get("id")
                cursor.execute(
                    "UPDATE payments SET status = 'refunded' WHERE id = ?",
                    (charge_id,)
                )

        if self.worker:
            self.worker.enqueue_job("AUDIT_EVENT", {
                "event_type": f"WEBHOOK_{event_type.upper()}",
                "payload": str(event_data)
            })

        return {"status": "processed", "event": event_type}
