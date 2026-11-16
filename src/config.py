"""
FinTech Payment Engine - Configuration Module
"""
import os

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0")
DATABASE_URL = os.environ.get("DATABASE_PATH", ":memory:")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "whsec_test_secret_key_849204810283")
ENVIRONMENT = os.environ.get("ENV", "production")
