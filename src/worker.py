"""
Asynchronous Worker & Background Task Queue
Simulates message broker / worker architectures (e.g., Celery / BullMQ)
for decoupling heavy side-effects from the critical payment path.
"""
import queue
import threading
import time
import logging

logger = logging.getLogger("PaymentWorker")

class BackgroundWorker:
    def __init__(self, conn_getter):
        self.task_queue = queue.Queue()
        self.conn_getter = conn_getter
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.task_queue.put(None)
        if self.thread:
            self.thread.join(timeout=1.0)

    def enqueue_job(self, task_type: str, data: dict):
        self.task_queue.put({"type": task_type, "data": data})

    def _run(self):
        while self.running:
            try:
                task = self.task_queue.get(timeout=0.2)
                if task is None:
                    break
                self._process_task(task)
                self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker task failed: {e}")

    def _process_task(self, task: dict):
        task_type = task["type"]
        data = task["data"]
        conn = self.conn_getter()
        
        if task_type == "GENERATE_INVOICE_PDF":
            # Simulate PDF generation & storage
            time.sleep(0.05)
            with conn:
                conn.execute(
                    "UPDATE invoices SET pdf_generated = 1 WHERE id = ?",
                    (data["invoice_id"],)
                )
        elif task_type == "AUDIT_EVENT":
            with conn:
                conn.execute(
                    "INSERT INTO audit_logs (event_type, payload) VALUES (?, ?)",
                    (data["event_type"], data["payload"])
                )
