"""
Transactional email sender — Resend (primary) with SMTP fallback.

Transactional = emails people EXPECT after signing up or paying:
  • Build started notifications
  • Site preview ready / approval gate
  • Payment confirmed
  • Site live celebration
  • Review requests (14-day, 30-day)
  • Referral drip (30-day post-live)
  • Steele internal approval alerts
  • Track B handoff zip delivery

Do NOT use for cold outreach to prospects who haven't paid.
Cold outreach → src/outreach/sender.py (Instantly.ai).

Resend free tier: 3,000 emails/month. Paid: $20/mo for 50k.
Sign up: https://resend.com  |  Python SDK: pip install resend
"""

import base64
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from src.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
    FROM_NAME, FROM_EMAIL, REPLY_TO, STEELE_EMAIL,
)

log = logging.getLogger(__name__)

_RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
_RESEND_FROM: str = os.getenv("RESEND_FROM_EMAIL", f"{FROM_NAME} <{FROM_EMAIL}>")


# ── Public API ────────────────────────────────────────────────────────────────

def send_transactional(
    to_email: str,
    subject: str,
    html: str,
    text: str = "",
    from_addr: str = "",
    reply_to: str = "",
    attachments: Optional[list[dict]] = None,
    lead_id: Optional[int] = None,
    log_to_crm: bool = False,
) -> bool:
    """
    Send a transactional email via Resend, falling back to SMTP.

    attachments: list of {"filename": str, "path": str | Path}
                 or {"filename": str, "content": bytes}

    lead_id + log_to_crm=True: logs the send to outreach_log.
    Returns True on success.
    """
    ok = (
        _via_resend(to_email, subject, html, text, from_addr, reply_to, attachments)
        if _RESEND_API_KEY
        else _via_smtp(to_email, subject, html, text, from_addr, reply_to)
    )

    if ok and log_to_crm and lead_id is not None:
        try:
            from src.crm.database import log_outreach
            log_outreach(lead_id, "email", subject, text or html, sender_email=_RESEND_FROM)
        except Exception as e:
            log.debug("CRM log failed for transactional send: %s", e)

    return ok


def send_to_steele(subject: str, text: str, html: str = "") -> bool:
    """Send an internal system alert to Steele's email."""
    return send_transactional(
        to_email=STEELE_EMAIL,
        subject=subject,
        html=html or f"<pre style='font-family:monospace;'>{text}</pre>",
        text=text,
    )


# ── Resend ────────────────────────────────────────────────────────────────────

def _via_resend(
    to_email: str,
    subject: str,
    html: str,
    text: str,
    from_addr: str,
    reply_to: str,
    attachments: Optional[list[dict]],
) -> bool:
    try:
        import resend
    except ImportError:
        log.error("resend package not installed — run: pip install resend")
        return _via_smtp(to_email, subject, html, text, from_addr, reply_to)

    resend.api_key = _RESEND_API_KEY

    params: dict = {
        "from": from_addr or _RESEND_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    if text:
        params["text"] = text
    if reply_to:
        params["reply_to"] = [reply_to]
    if attachments:
        params["attachments"] = _prepare_attachments(attachments)

    try:
        result = resend.Emails.send(params)
        email_id = getattr(result, "id", None) or (result.get("id") if isinstance(result, dict) else "?")
        log.info("Resend → %s (id=%s)", to_email, email_id)
        return True
    except Exception as e:
        log.error("Resend failed for %s: %s — falling back to SMTP", to_email, e)
        return _via_smtp(to_email, subject, html, text, from_addr, reply_to)


def _prepare_attachments(attachments: list[dict]) -> list[dict]:
    """Convert attachment dicts to Resend's expected format."""
    out = []
    for a in attachments:
        filename = a.get("filename", "attachment")
        if "path" in a:
            path = Path(a["path"])
            content = list(path.read_bytes())
        elif "content" in a and isinstance(a["content"], bytes):
            content = list(a["content"])
        elif "content" in a:
            content = a["content"]  # already a list
        else:
            continue
        out.append({"filename": filename, "content": content})
    return out


# ── SMTP fallback ─────────────────────────────────────────────────────────────

def _via_smtp(
    to_email: str,
    subject: str,
    html: str,
    text: str,
    from_addr: str = "",
    reply_to: str = "",
) -> bool:
    """SMTP fallback used when RESEND_API_KEY is not set."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr or f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Reply-To"] = reply_to or REPLY_TO

        if text:
            msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        log.info("SMTP fallback → %s", to_email)
        return True
    except Exception as e:
        log.error("SMTP fallback failed for %s: %s", to_email, e)
        return False
