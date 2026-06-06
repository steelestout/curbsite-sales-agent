"""
CAN-SPAM compliance — required for all outbound cold email.

Every outbound email must include:
  1. Physical mailing address in the footer (CURBSITE_ADDRESS from .env)
  2. One-click unsubscribe link with HMAC token
  3. List-Unsubscribe and List-Unsubscribe-Post headers

Leads marked 'unsubscribed' or 'bounced' are permanently blocked.
"""

import hashlib
import hmac
import logging
import os
from email.mime.multipart import MIMEMultipart

from src.crm.database import get_conn, update_lead_status

log = logging.getLogger(__name__)

_SECRET = os.getenv("UNSUBSCRIBE_SECRET", "change-me-set-UNSUBSCRIBE_SECRET-in-dotenv").encode()
_BASE_URL = os.getenv("DASHBOARD_URL", "http://localhost:5050")
_ADDRESS = os.getenv(
    "CURBSITE_ADDRESS",
    "Curbsite.co · Kokomo, IN 46902 · United States",
)


# ── Token helpers ─────────────────────────────────────────────────────────────

def _unsub_token(lead_id: int) -> str:
    """HMAC-SHA256 token for unsubscribe URL (first 20 hex chars)."""
    return hmac.new(_SECRET, str(lead_id).encode(), digestmod=hashlib.sha256).hexdigest()[:20]


def unsubscribe_url(lead_id: int) -> str:
    """One-click unsubscribe URL for this lead."""
    return f"{_BASE_URL}/unsubscribe?t={_unsub_token(lead_id)}&lid={lead_id}"


def verify_unsubscribe_token(token: str, lead_id: int) -> bool:
    """True if the token is valid for this lead_id (constant-time comparison)."""
    expected = _unsub_token(lead_id)
    return hmac.compare_digest(expected, token)


# ── Email mutation helpers ────────────────────────────────────────────────────

def add_compliance_footer(body: str, lead_id: int) -> str:
    """Append the required CAN-SPAM physical address and unsubscribe link."""
    unsub = unsubscribe_url(lead_id)
    footer = (
        f"\n\n---\n"
        f"{_ADDRESS}\n"
        f"To unsubscribe from future emails, click here: {unsub}"
    )
    return body + footer


def add_compliance_headers(msg: MIMEMultipart, lead_id: int) -> None:
    """Add RFC-compliant List-Unsubscribe headers to a MIME message."""
    unsub = unsubscribe_url(lead_id)
    msg["List-Unsubscribe"] = f"<{unsub}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"


# ── Lead status guards ────────────────────────────────────────────────────────

def is_unsubscribed(lead_id: int) -> bool:
    """True if this lead has opted out. Never email them again."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM leads WHERE id=?", (lead_id,)
        ).fetchone()
    return bool(row) and row["status"] == "unsubscribed"


def is_bounced(lead_id: int) -> bool:
    """True if any previous email to this lead hard-bounced."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM outreach_log WHERE lead_id=? AND bounced=1",
            (lead_id,),
        ).fetchone()
    return (row["n"] if row else 0) > 0


def mark_bounced(lead_id: int) -> None:
    """Record a hard bounce on the latest email log and update lead status."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE outreach_log SET bounced=1
               WHERE id = (
                   SELECT id FROM outreach_log
                   WHERE lead_id=? AND type='email'
                   ORDER BY sent_at DESC LIMIT 1
               )""",
            (lead_id,),
        )
    update_lead_status(lead_id, "bounced")
    log.warning("Lead #%d hard-bounced — permanently blocked from further sends.", lead_id)


def mark_unsubscribed(lead_id: int) -> None:
    """Mark a lead as unsubscribed so they are never contacted again."""
    update_lead_status(lead_id, "unsubscribed")
    log.info("Lead #%d unsubscribed.", lead_id)
