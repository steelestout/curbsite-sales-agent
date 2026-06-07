"""
Square webhook signature verification.

The actual /webhook/square Flask route is registered in stripe_webhook.py
so both payment processors share the same Flask app on port 5001.

Square webhook setup:
  Endpoint: https://curbsite.co/webhook/square
  Events:   payment.completed

Set SQUARE_WEBHOOK_SIGNATURE_KEY in .env (from Square Developer Dashboard →
your application → Webhooks → signature key).
"""

import base64
import hmac
import hashlib


def verify_square_signature(
    payload_body: bytes,
    signature_header: str,
    sig_key: str,
) -> bool:
    """Return True if the Square HMAC-SHA256 signature matches the payload."""
    expected = base64.b64encode(
        hmac.new(sig_key.encode(), payload_body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)
