"""
Cold outreach email sender — Instantly.ai (primary) with SMTP fallback.

Instantly.ai is purpose-built for cold email: it handles inbox warming,
account rotation, deliverability monitoring, reply detection, and unsubscribe
compliance. This is the right tool for reaching prospects who haven't signed up.

Architecture decision:
  INSTANTLY_API_KEY set  →  cold email routed through Instantly.ai
  INSTANTLY_API_KEY unset → SMTP multi-account fallback (warmup + rate limits)

Two Instantly send modes (set via INSTANTLY_CAMPAIGN_ID in .env):
  Campaign mode  (INSTANTLY_CAMPAIGN_ID set):
    Add the prospect to an Instantly campaign. Instantly controls scheduling,
    warming, rotation, and multi-step follow-up sequences automatically.
    This is the recommended mode for cold outreach sequences.

  Direct send mode (INSTANTLY_CAMPAIGN_ID not set):
    Use Instantly's email send API to dispatch a one-off email through
    a connected inbox. Useful for single-shot sends outside of a campaign.

Compliance guardrails (enforced regardless of which path is used):
  • Unsubscribed leads → permanently blocked
  • Hard-bounced leads → permanently blocked
  • CAN-SPAM footer injected by compliance.py
  • Every send logged to outreach_log in the CRM

Sign up: https://instantly.ai  |  API docs: https://developer.instantly.ai
Pricing: ~$37/mo for Hypergrowth (unlimited accounts + warming included)
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

_INSTANTLY_API_KEY: str = os.getenv("INSTANTLY_API_KEY", "")
_INSTANTLY_CAMPAIGN_ID: str = os.getenv("INSTANTLY_CAMPAIGN_ID", "")
_INSTANTLY_FROM_EMAIL: str = os.getenv("INSTANTLY_FROM_EMAIL", FROM_EMAIL)

# Round-robin cursor for SMTP fallback
_account_cursor = 0


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
    Send a cold outreach email to a prospect.

    Routes through Instantly.ai if INSTANTLY_API_KEY is set, otherwise falls
    back to SMTP multi-account rotation with warmup rate limits.

    plain_text_only=True strips HTML — use this for initial cold emails.
    Returns True on success or queue. False only on hard failures.
    """
    # Hard compliance blocks
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

    if _INSTANTLY_API_KEY:
        return _send_via_instantly(lead_id, to_email, subject, body, html_body)

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
    """Compatibility shim — rate limits are now DB-based or managed by Instantly."""
    log.debug("reset_daily_counter: no-op (limits are managed by Instantly or the DB).")


# ── Instantly.ai ──────────────────────────────────────────────────────────────

def _send_via_instantly(
    lead_id: int,
    to_email: str,
    subject: str,
    body: str,
    html_body: str,
) -> bool:
    """
    Route a cold email through Instantly.ai.

    Campaign mode (INSTANTLY_CAMPAIGN_ID set):
      Adds the prospect to an Instantly campaign. Instantly controls the send
      schedule, inbox warming, account rotation, and follow-up steps.
      Recommended for systematic outreach sequences.

    Direct send mode (no campaign ID):
      Sends a one-off email immediately through a connected Instantly inbox.
      Use for ad-hoc single sends.
    """
    if _INSTANTLY_CAMPAIGN_ID:
        return _instantly_add_to_campaign(lead_id, to_email)
    return _instantly_direct_send(lead_id, to_email, subject, body, html_body)


def _instantly_add_to_campaign(lead_id: int, to_email: str) -> bool:
    """
    Add a prospect to an Instantly campaign.
    Instantly handles scheduling, warming, rotation, and multi-step follow-ups.

    API: POST https://api.instantly.ai/api/v1/lead/add
    Docs: https://developer.instantly.ai/leads/add-leads-to-a-campaign
    """
    try:
        import requests
    except ImportError:
        log.error("requests package required — run: pip install requests")
        return False

    payload = {
        "api_key": _INSTANTLY_API_KEY,
        "campaign_id": _INSTANTLY_CAMPAIGN_ID,
        "email": to_email,
        "personalization_fields": {"lead_id": str(lead_id)},
    }

    try:
        resp = requests.post(
            "https://api.instantly.ai/api/v1/lead/add",
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            log.info(
                "Lead #%d (%s) added to Instantly campaign %s",
                lead_id, to_email, _INSTANTLY_CAMPAIGN_ID,
            )
            log_outreach(lead_id, "email", "via Instantly campaign", "", sender_email="instantly")
            update_lead_status(lead_id, "emailed")
            return True

        log.warning(
            "Instantly campaign add failed (%d): %s",
            resp.status_code, resp.text[:300],
        )
    except Exception as e:
        log.error("Instantly campaign add error: %s", e)

    log.info("Falling back to SMTP for lead #%d", lead_id)
    return False


def _instantly_direct_send(
    lead_id: int,
    to_email: str,
    subject: str,
    body: str,
    html_body: str,
) -> bool:
    """
    Send a one-off email through Instantly's connected inboxes.

    API: POST https://api.instantly.ai/api/v2/emails/send
    Docs: https://developer.instantly.ai/emails/send-email
    """
    try:
        import requests
    except ImportError:
        log.error("requests package required — run: pip install requests")
        return False

    headers = {
        "Authorization": f"Bearer {_INSTANTLY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": to_email,
        "subject": subject,
        "body": html_body or body,
        "plain_body": body,
        "reply_to": REPLY_TO,
    }
    if _INSTANTLY_FROM_EMAIL:
        payload["from_email"] = _INSTANTLY_FROM_EMAIL

    try:
        resp = requests.post(
            "https://api.instantly.ai/api/v2/emails/send",
            json=payload,
            headers=headers,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            data = resp.json() if resp.text else {}
            log.info(
                "Instantly direct send to %s (lead #%d) — id: %s",
                to_email, lead_id, data.get("id", "?"),
            )
            log_outreach(lead_id, "email", subject, body, sender_email="instantly")
            update_lead_status(lead_id, "emailed")
            return True

        log.warning(
            "Instantly direct send failed (%d): %s",
            resp.status_code, resp.text[:300],
        )
    except Exception as e:
        log.error("Instantly direct send error: %s", e)

    log.info("Falling back to SMTP for lead #%d", lead_id)
    return _send_via_smtp_rotation(lead_id, to_email, subject, body, html_body)


# ── SMTP multi-account fallback ───────────────────────────────────────────────
# Used when INSTANTLY_API_KEY is not set. Implements:
#   • Account rotation via SENDER_ACCOUNTS JSON (see .env.example)
#   • Warmup-aware daily caps (src.outreach.warmup)
#   • Business hours gate + domain cooldown (src.outreach.deliverability)
#   • DB queue when all accounts are at daily cap

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
