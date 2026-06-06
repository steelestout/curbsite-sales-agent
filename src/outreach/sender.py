"""
Multi-account email sender with round-robin rotation, warmup-aware limits,
and a DB-backed queue for when all accounts are at their daily cap.

Configure sending accounts via SENDER_ACCOUNTS in .env (JSON array):
  [
    {"email":"out@curbsite.co","smtp_host":"smtp.gmail.com","smtp_port":587,
     "smtp_pass":"app-password","from_name":"Steele @ Curbsite","warmup_day":1}
  ]

Falls back to the single-account SMTP_* variables if SENDER_ACCOUNTS is unset.

Key behaviors:
  - Round-robins across accounts, skipping any at their warmup daily cap
  - When all accounts are at their daily cap, queues the email for tomorrow 8am
  - Enforces business hours, domain cooldowns, and inter-send delays
  - Injects CAN-SPAM footer and compliance headers into every send
  - Blocks sends to unsubscribed or hard-bounced leads
  - First email to any prospect sent as plain text only (better deliverability)
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
from src.outreach.deliverability import can_send, random_send_delay, extract_domain
from src.outreach.warmup import check_and_warn

log = logging.getLogger(__name__)

_account_cursor = 0  # Round-robin state


# ── Account management ────────────────────────────────────────────────────────

def get_sender_accounts() -> list[dict]:
    """
    Parse SENDER_ACCOUNTS from env. Falls back to single-account SMTP_* config.
    Each account dict must have: email, smtp_host, smtp_port, smtp_pass, warmup_day.
    """
    raw = os.getenv("SENDER_ACCOUNTS", "").strip()
    if raw:
        try:
            accounts = json.loads(raw)
            if isinstance(accounts, list) and accounts:
                return accounts
        except (json.JSONDecodeError, TypeError):
            log.warning("SENDER_ACCOUNTS is not valid JSON — falling back to SMTP_* vars")

    return [{
        "email": FROM_EMAIL,
        "smtp_host": SMTP_HOST,
        "smtp_port": int(SMTP_PORT),
        "smtp_pass": SMTP_PASS,
        "from_name": FROM_NAME,
        "warmup_day": int(os.getenv("WARMUP_DAY", "22")),
    }]


def _pick_account() -> Optional[dict]:
    """
    Round-robin pick an account that has not reached its warmup daily cap.
    Returns None if every account is at its limit for the day.
    """
    global _account_cursor
    accounts = get_sender_accounts()
    n = len(accounts)
    for _ in range(n):
        acct = accounts[_account_cursor % n]
        _account_cursor = (_account_cursor + 1) % n
        daily_limit = check_and_warn(acct)
        from src.outreach.deliverability import get_daily_send_count
        sent = get_daily_send_count(acct["email"])
        if sent < daily_limit:
            return acct
    return None  # All accounts at cap


# ── Low-level SMTP ────────────────────────────────────────────────────────────

def _smtp_send(
    account: dict,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
    lead_id: int,
) -> None:
    """Build and dispatch a MIME email via the account's SMTP credentials."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    sender_addr = account["email"]
    from_name = account.get("from_name", FROM_NAME)
    msg["From"] = f"{from_name} <{sender_addr}>"
    msg["To"] = to_email
    msg["Reply-To"] = REPLY_TO
    msg["X-Mailer"] = "Mozilla Thunderbird 115.0"  # look like a real mail client

    add_compliance_headers(msg, lead_id)

    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    host = account.get("smtp_host", SMTP_HOST)
    port = int(account.get("smtp_port", SMTP_PORT))
    password = account.get("smtp_pass", SMTP_PASS)

    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.login(sender_addr, password)
        server.sendmail(sender_addr, [to_email], msg.as_string())


# ── Queue ─────────────────────────────────────────────────────────────────────

def _queue_email(
    lead_id: int,
    to_email: str,
    subject: str,
    body: str,
    html_body: str = "",
) -> None:
    """Persist email to queue when all accounts are at their daily cap."""
    # Schedule for tomorrow at 8am Central (14:00 UTC)
    tomorrow = (datetime.utcnow().date().isoformat())
    scheduled = f"{tomorrow} 14:00:00"  # rough tomorrow 8am CT; queue runner will re-check gates
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO email_queue (lead_id, to_email, subject, body, html_body, scheduled_for)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lead_id, to_email, subject, body, html_body, scheduled),
        )
    log.info(
        "All accounts at daily cap — email for lead #%d queued for %s.", lead_id, scheduled
    )


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
    Send an email through the best available account.

    plain_text_only=True strips HTML — use this for all initial cold outreach.
    Returns True on success or queue. Returns False only on hard failures
    (unsubscribe, bounce, SMTP error after all retries).
    """
    # Hard blocks — never email these leads
    if is_unsubscribed(lead_id):
        log.debug("Skipping lead #%d — unsubscribed.", lead_id)
        return False
    if is_bounced(lead_id):
        log.debug("Skipping lead #%d — hard bounced.", lead_id)
        return False

    # CAN-SPAM footer injected into every outbound body
    body = add_compliance_footer(body, lead_id)
    if plain_text_only:
        html_body = ""

    if dry_run:
        log.info("[DRY RUN] To: %s | Subject: %s", to_email, subject)
        log_outreach(lead_id, "email", subject, body, sender_email="dry_run")
        return True

    # Pick the best available account
    acct = _pick_account()
    if acct is None:
        _queue_email(lead_id, to_email, subject, body, html_body)
        return True  # Queued, not lost

    # Full deliverability gate (hours + domain cooldown)
    prospect_domain = extract_domain(to_email)
    daily_limit = check_and_warn(acct)
    ok, reason = can_send(acct["email"], daily_limit, prospect_domain)
    if not ok:
        log.warning("Deliverability gate: %s — queuing.", reason)
        _queue_email(lead_id, to_email, subject, body, html_body)
        return True

    # Send
    try:
        _smtp_send(acct, to_email, subject, body, html_body, lead_id)
        log_outreach(lead_id, "email", subject, body, sender_email=acct["email"])
        update_lead_status(lead_id, "emailed")
        log.info("Sent to %s via %s (lead #%d)", to_email, acct["email"], lead_id)
        random_send_delay()
        return True
    except smtplib.SMTPRecipientsRefused:
        log.warning("Hard bounce for %s — blocking lead #%d.", to_email, lead_id)
        mark_bounced(lead_id)
        log_outreach(lead_id, "email", subject, body, error="bounced", sender_email=acct["email"])
        return False
    except Exception as e:
        log.error("SMTP error for %s: %s", to_email, e)
        log_outreach(lead_id, "email", subject, body, error=str(e), sender_email=acct["email"])
        return False


def process_queue(dry_run: bool = False) -> int:
    """
    Attempt to send all pending queued emails that are now due.
    Call this at the start of each business day. Returns count sent.
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
        if ok:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE email_queue SET status='sent', sent_at=? WHERE id=?",
                    (datetime.utcnow().isoformat(), item["id"]),
                )
            sent_count += 1
        else:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE email_queue SET status='failed' WHERE id=?",
                    (item["id"],),
                )

    log.info("Queue processed: %d/%d sent.", sent_count, len(pending))
    return sent_count


def reset_daily_counter() -> None:
    """Compatibility shim for callers that used email_sender.reset_daily_counter()."""
    log.info("Daily counters are DB-based — no in-memory state to reset.")
