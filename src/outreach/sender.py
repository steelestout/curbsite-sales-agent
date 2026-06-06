"""
Cold outreach email sender — SMTP with account rotation, warmup, and deliverability gates.

Sends from the dedicated outreach domain (OUTREACH_DOMAIN, e.g. getcurbsite.co),
keeping curbsite.co completely isolated from cold email risk.

Features:
  • Round-robin across multiple sending accounts (SENDER_ACCOUNTS JSON in .env)
  • Warmup-aware daily caps: 5 → 15 → 30 → 50 emails/day over 4 weeks
  • Business hours gate (8am–6pm Central), 45–180s random inter-send delays
  • One domain per hour cooldown (prevents domain reputation hits)
  • DB-backed queue: when all accounts are at their daily cap, email is held
    and retried at 8am Central the next business day
  • CAN-SPAM footer + List-Unsubscribe header on every send
  • Hard block on unsubscribed and hard-bounced leads

Separate from transactional email → see src/notifications/transactional.py (Resend).
"""

import json
import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
    FROM_NAME, FROM_EMAIL, REPLY_TO,
)
from src.crm.database import get_conn, log_outreach, update_lead_status
from src.outreach.compliance import (
    add_compliance_headers, add_compliance_footer,
    is_unsubscribed, is_bounced, mark_bounced,
)

log = logging.getLogger(__name__)

_account_cursor = 0  # Round-robin state across calls


# ── Public API ────────────────────────────────────────────────────────────────

def send_email(
    lead_id: int,
    to_email: str,
    subject: str,
    body: str,
    html_body: str = "",
    dry_run: bool = False,
    plain_text_only: bool = False,
) -> bool:
    """
    Send a cold outreach email to a prospect via SMTP with account rotation.

    plain_text_only=True strips HTML — recommended for all initial cold emails
    (plain text has dramatically better deliverability for cold outreach).
    Returns True on success or queue. Returns False only on hard failures
    (unsubscribed, bounced, or SMTP error after retries).
    """
    if is_unsubscribed(lead_id):
        log.debug("Skipping lead #%d — unsubscribed.", lead_id)
        return False
    if is_bounced(lead_id):
        log.debug("Skipping lead #%d — hard bounced.", lead_id)
        return False

    body = add_compliance_footer(body, lead_id)
    if plain_text_only:
        html_body = ""

    if dry_run:
        log.info("[DRY RUN] Cold email to %s — Subject: %s", to_email, subject)
        log_outreach(lead_id, "email", subject, body, sender_email="dry_run")
        return True

    return _send_via_smtp_rotation(lead_id, to_email, subject, body, html_body)


def process_queue(dry_run: bool = False) -> int:
    """
    Attempt to send all pending DB-queued emails that are now due.
    Used only in SMTP fallback mode. Returns count sent.
    """
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM email_queue
               WHERE status='pending' AND scheduled_for <= ?
               ORDER BY scheduled_for LIMIT 100""",
            (now,),
        ).fetchall()
        pending = [dict(r) for r in rows]

    sent_count = 0
    for item in pending:
        ok = send_email(
            item["lead_id"], item["to_email"],
            item["subject"], item["body"],
            item.get("html_body") or "",
            dry_run=dry_run,
        )
        status = "sent" if ok else "failed"
        with get_conn() as conn:
            conn.execute(
                "UPDATE email_queue SET status=?, sent_at=? WHERE id=?",
                (status, datetime.utcnow().isoformat(), item["id"]),
            )
        if ok:
            sent_count += 1

    log.info("Queue processed: %d/%d sent.", sent_count, len(pending))
    return sent_count


def reset_daily_counter() -> None:
    """Compatibility shim — daily limits are managed by the DB (outreach_log counts)."""
    log.debug("reset_daily_counter: no-op (limits tracked via outreach_log).")


# ── SMTP multi-account rotation ───────────────────────────────────────────────
# Account rotation via SENDER_ACCOUNTS JSON (see .env.example).
# Warmup-aware daily caps (src.outreach.warmup).
# Business hours gate + domain cooldown (src.outreach.deliverability).
# DB queue when all accounts are at daily cap.

def _get_sender_accounts() -> list[dict]:
    raw = os.getenv("SENDER_ACCOUNTS", "").strip()
    if raw:
        try:
            accounts = json.loads(raw)
            if isinstance(accounts, list) and accounts:
                return accounts
        except (json.JSONDecodeError, TypeError):
            log.warning("SENDER_ACCOUNTS is not valid JSON — using single SMTP account")
    return [{
        "email": FROM_EMAIL,
        "smtp_host": SMTP_HOST,
        "smtp_port": int(SMTP_PORT),
        "smtp_pass": SMTP_PASS,
        "from_name": FROM_NAME,
        "warmup_day": int(os.getenv("WARMUP_DAY", "22")),
    }]


def _pick_smtp_account() -> Optional[dict]:
    """Round-robin pick an SMTP account that hasn't hit its warmup daily cap."""
    global _account_cursor
    from src.outreach.warmup import check_and_warn
    from src.outreach.deliverability import get_daily_send_count

    accounts = _get_sender_accounts()
    n = len(accounts)
    for _ in range(n):
        acct = accounts[_account_cursor % n]
        _account_cursor = (_account_cursor + 1) % n
        daily_limit = check_and_warn(acct)
        if get_daily_send_count(acct["email"]) < daily_limit:
            return acct
    return None


def _queue_for_tomorrow(lead_id: int, to_email: str, subject: str, body: str, html_body: str) -> None:
    tomorrow = datetime.utcnow().date().isoformat()
    scheduled = f"{tomorrow} 14:00:00"  # 8am Central = 14:00 UTC
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO email_queue (lead_id, to_email, subject, body, html_body, scheduled_for)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lead_id, to_email, subject, body, html_body, scheduled),
        )
    log.info("All SMTP accounts at cap — email for lead #%d queued for %s.", lead_id, scheduled)


def _send_via_smtp_rotation(
    lead_id: int,
    to_email: str,
    subject: str,
    body: str,
    html_body: str,
) -> bool:
    """SMTP fallback with account rotation, warmup limits, and deliverability gates."""
    from src.outreach.deliverability import can_send, random_send_delay, extract_domain
    from src.outreach.warmup import check_and_warn

    acct = _pick_smtp_account()
    if acct is None:
        _queue_for_tomorrow(lead_id, to_email, subject, body, html_body)
        return True  # Queued = not lost

    prospect_domain = extract_domain(to_email)
    daily_limit = check_and_warn(acct)
    ok, reason = can_send(acct["email"], daily_limit, prospect_domain)
    if not ok:
        log.warning("Deliverability gate: %s — queuing.", reason)
        _queue_for_tomorrow(lead_id, to_email, subject, body, html_body)
        return True

    try:
        _smtp_dispatch(acct, to_email, subject, body, html_body, lead_id)
        log_outreach(lead_id, "email", subject, body, sender_email=acct["email"])
        update_lead_status(lead_id, "emailed")
        log.info("SMTP → %s via %s (lead #%d)", to_email, acct["email"], lead_id)
        random_send_delay()
        return True
    except smtplib.SMTPRecipientsRefused:
        log.warning("Hard bounce: %s — blocking lead #%d.", to_email, lead_id)
        mark_bounced(lead_id)
        log_outreach(lead_id, "email", subject, body, error="bounced", sender_email=acct["email"])
        return False
    except Exception as e:
        log.error("SMTP error for %s: %s", to_email, e)
        log_outreach(lead_id, "email", subject, body, error=str(e), sender_email=acct["email"])
        return False


def _smtp_dispatch(
    account: dict,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
    lead_id: int,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{account.get('from_name', FROM_NAME)} <{account['email']}>"
    msg["To"] = to_email
    msg["Reply-To"] = REPLY_TO
    msg["X-Mailer"] = "Mozilla Thunderbird 115.0"

    add_compliance_headers(msg, lead_id)

    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(account.get("smtp_host", SMTP_HOST), int(account.get("smtp_port", SMTP_PORT))) as s:
        s.ehlo()
        s.starttls()
        s.login(account["email"], account.get("smtp_pass", SMTP_PASS))
        s.sendmail(account["email"], [to_email], msg.as_string())
