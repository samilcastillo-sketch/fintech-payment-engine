"""
Database layer with ACID transactional guarantees and SQLite WAL mode.
"""
import sqlite3
import threading

_local = threading.local()

def get_connection(db_path=":memory:"):
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            if db_path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL;")
        _local.conn = conn
    return _local.conn

def init_db(conn):
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            stock INTEGER NOT NULL CHECK(stock >= 0)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            status TEXT NOT NULL CHECK(status IN ('pending', 'succeeded', 'failed', 'refunded')),
            idempotency_key TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            payment_id TEXT NOT NULL REFERENCES payments(id),
            invoice_number TEXT UNIQUE NOT NULL,
            amount_cents INTEGER NOT NULL,
            pdf_generated INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS idempotency_records (
            key TEXT PRIMARY KEY,
            request_hash TEXT NOT NULL,
            response_code INTEGER NOT NULL,
            response_body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
