"""
Email deliverability — rate limiting, business hours enforcement, and domain cooldowns.

Rules enforced before every send:
  • Business hours only: 8am–6pm Central (hard gate)
  • Daily cap per account from warmup schedule (hard-stop)
  • One email per domain per hour (prevents domain reputation hits)
  • Random 45–180s inter-send delay to mimic human pacing
"""

import logging
import random
import time
from datetime import date, datetime

from src.crm.database import get_conn

log = logging.getLogger(__name__)

_BIZ_HOUR_START = 8   # 8 AM Central
_BIZ_HOUR_END = 18    # 6 PM Central
_CENTRAL_UTC_OFFSET = -6  # CST (approximation; ignores DST for simplicity)
_DELAY_MIN = 45
_DELAY_MAX = 180


# ── Time helpers ──────────────────────────────────────────────────────────────

def _central_hour() -> int:
    """Return the current hour in US Central Standard Time (UTC-6)."""
    return (datetime.utcnow().hour + _CENTRAL_UTC_OFFSET) % 24


def is_business_hours() -> bool:
    """True if the current time is between 8am and 6pm Central."""
    h = _central_hour()
    return _BIZ_HOUR_START <= h < _BIZ_HOUR_END


def seconds_until_open() -> int:
    """Seconds until 8am Central. Returns 0 if already in business hours."""
    if is_business_hours():
        return 0
    h = _central_hour()
    if h < _BIZ_HOUR_START:
        return (_BIZ_HOUR_START - h) * 3600
    return (24 - h + _BIZ_HOUR_START) * 3600


def random_send_delay() -> None:
    """Sleep 45–180 seconds between sends to mimic human pacing."""
    delay = random.uniform(_DELAY_MIN, _DELAY_MAX)
    log.debug("Inter-send delay: %.0fs", delay)
    time.sleep(delay)


# ── Database checks ───────────────────────────────────────────────────────────

def get_daily_send_count(account_email: str) -> int:
    """Count successful outbound emails sent from this account today."""
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as n FROM outreach_log
               WHERE sender_email=? AND type='email'
               AND date(sent_at)=?
               AND (error IS NULL OR error='')""",
            (account_email, today),
        ).fetchone()
    return row["n"] if row else 0


def domain_sent_this_hour(sender_email: str, prospect_domain: str) -> bool:
    """True if this sender already emailed @<prospect_domain> in the last hour."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as n
               FROM outreach_log ol
               JOIN leads l ON l.id = ol.lead_id
               WHERE ol.sender_email=? AND ol.type='email'
               AND lower(l.email) LIKE ?
               AND datetime(ol.sent_at) >= datetime('now', '-1 hour')""",
            (sender_email, f"%@{prospect_domain.lower()}"),
        ).fetchone()
    return (row["n"] if row else 0) > 0


# ── Gate ──────────────────────────────────────────────────────────────────────

def can_send(
    account_email: str,
    daily_limit: int,
    prospect_domain: str = "",
) -> tuple[bool, str]:
    """
    Check all deliverability gates before a send.
    Returns (allowed, reason_if_blocked).
    """
    if not is_business_hours():
        h = _central_hour()
        return False, f"Outside business hours — Central hour is {h:02d}:xx"

    sent = get_daily_send_count(account_email)
    if sent >= daily_limit:
        return False, f"Daily cap reached: {sent}/{daily_limit} for {account_email}"

    if prospect_domain and domain_sent_this_hour(account_email, prospect_domain):
        return False, f"Domain cooldown: already sent to @{prospect_domain} this hour"

    return True, ""


# ── Utility ───────────────────────────────────────────────────────────────────

def extract_domain(email_address: str) -> str:
    """Extract the domain portion of an email address."""
    if "@" in email_address:
        return email_address.split("@", 1)[1].lower().strip()
    return ""
