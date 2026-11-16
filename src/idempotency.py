"""
Idempotency Engine
Prevents double-charging in payment processing by caching and replaying
responses based on a unique client-provided idempotency key.
"""
import hashlib
import json
import sqlite3
from typing import Optional, Tuple

class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different request payload."""
    pass

class IdempotencyManager:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_cached_response(self, key: str, payload_str: str) -> Optional[Tuple[int, dict]]:
        request_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT request_hash, response_code, response_body FROM idempotency_records WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        saved_hash, status_code, body = row["request_hash"], row["response_code"], row["response_body"]
        if saved_hash != request_hash:
            raise IdempotencyConflictError("Idempotency key reused with different request payload.")
        
        return status_code, json.loads(body)

    def save_response(self, key: str, payload_str: str, status_code: int, response_dict: dict):
        request_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_records 
                (key, request_hash, response_code, response_body)
                VALUES (?, ?, ?, ?)
                """,
                (key, request_hash, status_code, json.dumps(response_dict))
            )
