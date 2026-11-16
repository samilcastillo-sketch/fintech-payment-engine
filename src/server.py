"""
RESTful API HTTP Server (Production Architecture)
Zero-dependency core: runs anywhere on modern Python 3.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
from urllib.parse import urlparse

from .config import PORT, HOST, DATABASE_URL, WEBHOOK_SECRET
from .database import get_connection, init_db
from .security import verify_webhook_signature
from .idempotency import IdempotencyManager, IdempotencyConflictError
from .services import PaymentService, InsufficientStockError, ProductNotFoundError
from .worker import BackgroundWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("PaymentAPI")

class PaymentAPIHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, data: dict, headers: dict = None):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        conn = get_connection(self.server.db_path)

        if parsed.path == "/api/v1/health":
            self._send_json(200, {
                "status": "healthy",
                "service": "fintech-payment-engine",
                "version": "1.0.0"
            })
        elif parsed.path == "/api/v1/products":
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, price_cents, stock FROM products")
            products = [dict(row) for row in cursor.fetchall()]
            self._send_json(200, {"products": products})
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        body_str = raw_body.decode("utf-8")

        conn = get_connection(self.server.db_path)
        service = PaymentService(conn, self.server.worker)
        idempotency_mgr = IdempotencyManager(conn)

        if parsed.path == "/api/v1/payments":
            idempotency_key = self.headers.get("X-Idempotency-Key")

            # Check for cached idempotent response
            if idempotency_key:
                try:
                    cached = idempotency_mgr.get_cached_response(idempotency_key, body_str)
                    if cached:
                        code, response_data = cached
                        return self._send_json(code, response_data, {"X-Cache": "HIT-IDEMPOTENT"})
                except IdempotencyConflictError as e:
                    return self._send_json(409, {"error": "Conflict", "detail": str(e)})

            try:
                data = json.loads(body_str) if body_str else {}
                customer_id = data.get("customer_id")
                product_id = data.get("product_id")
                quantity = int(data.get("quantity", 1))

                if not customer_id or not product_id:
                    return self._send_json(400, {"error": "Missing required fields: customer_id, product_id"})

                result = service.process_checkout(
                    customer_id=customer_id,
                    product_id=product_id,
                    quantity=quantity,
                    idempotency_key=idempotency_key
                )

                if idempotency_key:
                    idempotency_mgr.save_response(idempotency_key, body_str, 201, result)

                return self._send_json(201, result)

            except InsufficientStockError as e:
                return self._send_json(409, {"error": "Insufficient Stock", "detail": str(e)})
            except ProductNotFoundError as e:
                return self._send_json(404, {"error": "Product Not Found", "detail": str(e)})
            except Exception as e:
                logger.error(f"Internal error: {e}", exc_info=True)
                return self._send_json(500, {"error": "Internal Server Error", "detail": str(e)})

        elif parsed.path == "/api/v1/webhooks/stripe":
            signature = self.headers.get("X-Stripe-Signature", "")
            if not verify_webhook_signature(raw_body, signature, WEBHOOK_SECRET):
                return self._send_json(401, {"error": "Invalid webhook signature"})

            try:
                data = json.loads(body_str)
                event_type = data.get("type", "unknown")
                event_data = data.get("data", {})
                res = service.handle_stripe_webhook_event(event_type, event_data)
                return self._send_json(200, res)
            except Exception as e:
                return self._send_json(400, {"error": "Malformed webhook payload", "detail": str(e)})

        else:
            self._send_json(404, {"error": "Not Found"})

def run_server(host=HOST, port=PORT, db_path=DATABASE_URL):
    conn = get_connection(db_path)
    init_db(conn)
    
    # Pre-populate sample inventory if empty
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO products VALUES ('prod_macbook', 'MacBook Pro M3', 199900, 10)")
            cursor.execute("INSERT INTO products VALUES ('prod_keyboard', 'Mechanical Keyboard', 12000, 2)")

    worker = BackgroundWorker(lambda: get_connection(db_path))
    worker.start()

    server = HTTPServer((host, port), PaymentAPIHandler)
    server.db_path = db_path
    server.worker = worker

    logger.info(f"Payment Engine API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
    finally:
        worker.stop()
        server.server_close()

if __name__ == "__main__":
    run_server()
