"""
Security & Cryptographic Verification Module
"""
import hmac
import hashlib

def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Validates HMAC SHA-256 signature using constant-time comparison
    to prevent timing attacks.
    """
    if not signature_header or not secret:
        return False
    
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature_header)

def compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Helper to compute HMAC SHA-256 for test or mock webhook dispatches."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
