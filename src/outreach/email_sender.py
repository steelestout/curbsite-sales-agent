"""
Email sender — SMTP with rate limiting and bounce tracking.
"""

import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASS,
    FROM_NAME,
    FROM_EMAIL,
    REPLY_TO,
    MAX_EMAILS_PER_DAY,
    OUTREACH_DELAY,
)
from src.crm.database import log_outreach, update_lead_status

log = logging.getLogger(__name__)

# Simple in-memory daily counter — resets when process restarts
_sent_today = 0


def _smtp_send(to_email: str, subject: str, body_text: str, body_html: str = "") -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Reply-To"] = REPLY_TO

    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [to_email], msg.as_string())


def send_email(
    lead_id: int,
    to_email: str,
    subject: str,
    body: str,
    html_body: str = "",
    dry_run: bool = False,
) -> bool:
    """
    Send an email to a lead. Returns True on success.

    dry_run=True logs the email without actually sending (useful for testing).
    """
    global _sent_today

    if _sent_today >= MAX_EMAILS_PER_DAY:
        log.warning("Daily email limit (%d) reached — skipping.", MAX_EMAILS_PER_DAY)
        return False

    if dry_run:
        log.info("[DRY RUN] Would send to %s — Subject: %s", to_email, subject)
        log.debug("[DRY RUN] Body:\n%s", body)
        log_outreach(lead_id, "email", subject, body)
        return True

    try:
        _smtp_send(to_email, subject, body, html_body)
        _sent_today += 1
        log_outreach(lead_id, "email", subject, body)
        update_lead_status(lead_id, "emailed")
        log.info("Email sent to %s (lead #%d)", to_email, lead_id)
        time.sleep(OUTREACH_DELAY)
        return True
    except smtplib.SMTPRecipientsRefused:
        log.warning("Bounced: %s", to_email)
        log_outreach(lead_id, "email", subject, body, error="bounced")
        return False
    except Exception as e:
        log.error("Failed sending to %s: %s", to_email, e)
        log_outreach(lead_id, "email", subject, body, error=str(e))
        return False


def reset_daily_counter() -> None:
    """Call this once per day via the scheduler."""
    global _sent_today
    _sent_today = 0
    log.info("Daily email counter reset.")
