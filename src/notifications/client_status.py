"""
Client-facing status emails — sent at each pipeline stage.

Stages:
  notify_build_started    — After 50% deposit; build is underway (to client)
  notify_review_ready     — After Steele approves; preview + payment link (to client)
  notify_payment_confirmed — Final payment received (to client)
  notify_site_live        — Site is live; URL, portal login, care plan (to client)

Steele approval gate:
  request_steele_approval — Preview email to Steele with Approve / Request Changes buttons
  approve_build(token)    — Called by dashboard; sends review_ready email to client
  reject_build(token)     — Called by dashboard; sets revision_needed flag

All HTML emails are single-column, mobile-first, Curbsite-branded.
"""

import logging
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
    FROM_NAME, FROM_EMAIL, REPLY_TO,
    AGENCY_NAME, AGENCY_URL,
    STEELE_EMAIL, DASHBOARD_URL, PORTAL_URL,
)
from src.crm.database import get_conn, get_lead, update_lead_status

log = logging.getLogger(__name__)

_GREEN = "#1b3a1b"
_BTN   = "#2e7d32"
_BTN_RED = "#b71c1c"


# ── Low-level email helper ────────────────────────────────────────────────────

def _send_html_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str = "",
) -> None:
    """Send an HTML email. Raises on failure (caller handles retry/logging)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Reply-To"] = REPLY_TO

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, [to_email], msg.as_string())


def _send_steele(subject: str, text: str, html: str = "") -> None:
    """Shortcut for system alerts to Steele."""
    _send_html_email(STEELE_EMAIL, subject, html or f"<pre>{text}</pre>", text)


# ── Shared email chrome ────────────────────────────────────────────────────────

def _wrap(inner_html: str) -> str:
    """Wrap inner HTML in the Curbsite email chrome (header + footer)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;">
<tr><td align="center" style="padding:24px 12px;">
<table width="100%" style="max-width:580px;background:#ffffff;border-radius:10px;
       overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1);">

  <!-- Header -->
  <tr><td style="background:{_GREEN};padding:24px 28px;">
    <span style="color:#ffffff;font-size:22px;font-weight:bold;letter-spacing:2px;">CURBSITE</span>
  </td></tr>

  <!-- Content -->
  <tr><td style="padding:32px 28px;">
    {inner_html}
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f0f0f0;padding:16px 28px;text-align:center;">
    <p style="color:#999;font-size:12px;margin:0;">
      {AGENCY_NAME} &middot;
      <a href="{AGENCY_URL}" style="color:#999;text-decoration:none;">{AGENCY_URL}</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _btn(url: str, label: str, color: str = "") -> str:
    bg = color or _BTN
    return (
        f'<a href="{url}" style="display:block;background:{bg};color:#ffffff;'
        f'text-decoration:none;text-align:center;padding:18px 24px;border-radius:8px;'
        f'font-size:18px;font-weight:bold;margin:24px 0;">{label}</a>'
    )


def _p(text: str, size: int = 16, color: str = "#333333") -> str:
    return (
        f'<p style="font-size:{size}px;color:{color};line-height:1.7;margin:0 0 16px;">'
        f"{text}</p>"
    )


# ── Approval token helpers ─────────────────────────────────────────────────────

def _create_token(lead_id: int, action: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(days=7)).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO approval_tokens (lead_id, token, action, expires_at)
               VALUES (?, ?, ?, ?)""",
            (lead_id, token, action, expires),
        )
    return token


def _use_token(token: str) -> dict | None:
    """
    Validate and consume an approval token.
    Returns the token row dict on success, None if invalid/expired/used.
    """
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM approval_tokens
               WHERE token=? AND used=0 AND expires_at > ?""",
            (token, now),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE approval_tokens SET used=1 WHERE token=?", (token,)
            )
    return dict(row) if row else None


# ── Client-facing status emails ───────────────────────────────────────────────

def notify_build_started(lead: dict) -> None:
    """Email client: we received your deposit, build is underway."""
    name = lead.get("owner_name") or lead.get("business_name", "there")
    first = name.split()[0]
    biz = lead.get("business_name", "your business")
    email = lead.get("email")
    if not email:
        return

    subject = f"We're building your site, {first}! 🎉"
    inner = (
        _p(f"Hey {first},", size=17, color="#1a1a1a")
        + _p("Great news — we received your deposit. Your site build has officially started!")
        + _p(
            f"Here's what happens next for <strong>{biz}</strong>:"
        )
        + """<ul style="font-size:16px;color:#333;line-height:2;padding-left:20px;margin:0 0 20px;">
          <li>We build your full site (usually 3–5 business days)</li>
          <li>Steele reviews it personally</li>
          <li>You get a preview link and a request for the final payment</li>
          <li>We make any tweaks you want — then launch!</li>
        </ul>"""
        + _p(
            "You'll hear from us again when your preview is ready. "
            "Feel free to reply to this email with any questions in the meantime.",
        )
        + _p(f"Excited to build something great for you,<br><strong>Steele @ Curbsite</strong>")
    )

    try:
        _send_html_email(email, subject, _wrap(inner), (
            f"Hey {first},\n\nWe received your deposit — your site build has started!\n\n"
            f"We'll send you a preview link in 3-5 business days.\n\nSteele @ Curbsite"
        ))
        log.info("Build-started email sent to %s (lead #%d)", email, lead["id"])
    except Exception as exc:
        log.error("Failed to send build-started email: %s", exc)


def notify_review_ready(lead: dict, preview_url: str, payment_url: str) -> None:
    """Email client: preview is ready + request final payment."""
    name = lead.get("owner_name") or lead.get("business_name", "there")
    first = name.split()[0]
    biz = lead.get("business_name", "your business")
    email = lead.get("email")
    if not email:
        return

    subject = f"Your {biz} site preview is ready!"
    inner = (
        _p(f"Hey {first},", size=17, color="#1a1a1a")
        + _p(
            f"Your website for <strong>{biz}</strong> is built and ready for your review. "
            "Click below to see it:"
        )
        + _btn(preview_url, "View Your Site Preview →")
        + _p(
            "Take a look and let me know if you'd like any changes — "
            "copy tweaks, color adjustments, photo swaps, anything at all. "
            "I'm here to get it exactly right."
        )
        + _p(
            "Once you're happy with it, please complete the final 50% payment "
            "to lock in your launch date:",
            color="#555",
        )
        + _btn(payment_url, "Pay Final 50% & Go Live →")
        + _p(
            "After payment, we'll do the final DNS setup and your site will be "
            "live within 24 hours.",
            size=14,
            color="#777",
        )
        + _p(f"Talk soon,<br><strong>Steele @ Curbsite</strong>")
    )

    try:
        _send_html_email(email, subject, _wrap(inner), (
            f"Hey {first},\n\nYour site preview is ready:\n{preview_url}\n\n"
            f"Let me know any changes, then complete the final payment to go live:\n{payment_url}\n\n"
            f"Steele @ Curbsite"
        ))
        log.info("Review-ready email sent to %s (lead #%d)", email, lead["id"])
    except Exception as exc:
        log.error("Failed to send review-ready email: %s", exc)


def notify_payment_confirmed(lead: dict) -> None:
    """Email client: final payment received, launch is coming."""
    name = lead.get("owner_name") or lead.get("business_name", "there")
    first = name.split()[0]
    biz = lead.get("business_name", "your business")
    email = lead.get("email")
    if not email:
        return

    subject = f"Payment confirmed — {biz} goes live soon!"
    inner = (
        _p(f"Hey {first},", size=17, color="#1a1a1a")
        + _p("We got your final payment — thank you! 🎉")
        + _p(
            f"We're now doing the final DNS configuration for <strong>{biz}</strong>. "
            "Your site will be live within <strong>24 hours</strong>. "
            "You'll get one more email with the live URL and your login details."
        )
        + _p(
            "If you're on a care plan, we'll also send you info about what's included "
            "and how to reach us for updates.",
            size=14,
            color="#555",
        )
        + _p(f"Almost there!<br><strong>Steele @ Curbsite</strong>")
    )

    try:
        _send_html_email(email, subject, _wrap(inner), (
            f"Hey {first},\n\nFinal payment confirmed! Your site goes live within 24 hours.\n\n"
            f"Watch for one more email with your live URL.\n\nSteele @ Curbsite"
        ))
        log.info("Payment-confirmed email sent to %s (lead #%d)", email, lead["id"])
    except Exception as exc:
        log.error("Failed to send payment-confirmed email: %s", exc)


def notify_site_live(lead: dict, site_url: str) -> None:
    """Email client: site is live! Include URL, portal login, and care plan info."""
    name = lead.get("owner_name") or lead.get("business_name", "there")
    first = name.split()[0]
    biz = lead.get("business_name", "your business")
    email = lead.get("email")
    if not email:
        return

    care_plan = lead.get("care_plan")
    care_section = ""
    if care_plan:
        care_section = f"""
        <div style="background:#f0f7f0;border-left:4px solid #2e7d32;padding:18px 20px;
                    border-radius:0 8px 8px 0;margin:20px 0;">
          <p style="font-size:15px;color:#1b3a1b;font-weight:bold;margin:0 0 8px;">
            Your Monthly Care Plan — ${care_plan:.0f}/mo
          </p>
          <ul style="font-size:14px;color:#333;line-height:1.8;padding-left:18px;margin:0;">
            <li>Hosting & SSL certificate</li>
            <li>Security updates & backups</li>
            <li>Content updates (up to 2/month)</li>
            <li>Priority email support</li>
          </ul>
        </div>"""

    inner = (
        _p(f"🚀 Your site is LIVE, {first}!", size=20, color="#1b3a1b")
        + _p(f"<strong>{biz}</strong> is officially on the internet!")
        + _btn(f"https://{lead.get('domain', site_url)}", f"Visit {biz} →")
        + _p(
            "Share it everywhere — Google Business Profile, Instagram bio, "
            "your email signature, the front door. The more traffic, the better.",
            color="#555",
        )
        + care_section
        + f"""<div style="background:#f9f9f9;padding:18px 20px;border-radius:8px;margin:20px 0;">
          <p style="font-size:15px;color:#333;font-weight:bold;margin:0 0 8px;">Client Portal</p>
          <p style="font-size:14px;color:#555;margin:0 0 8px;">
            Manage your files and submit update requests at:
          </p>
          <a href="{PORTAL_URL}" style="color:#2e7d32;font-size:14px;">{PORTAL_URL}</a>
        </div>"""
        + _p(
            "Reply to this email any time — I'm always here. "
            "It's been a pleasure building this for you.",
        )
        + _p(f"Congrats!<br><strong>Steele @ Curbsite</strong>")
    )

    try:
        _send_html_email(email, subject := f"Your site is LIVE — {biz}", _wrap(inner), (
            f"Hey {first},\n\nYour site is LIVE!\n\nhttps://{lead.get('domain', site_url)}\n\n"
            f"Client portal: {PORTAL_URL}\n\nCongrats!\nSteele @ Curbsite"
        ))
        log.info("Site-live email sent to %s (lead #%d)", email, lead["id"])
    except Exception as exc:
        log.error("Failed to send site-live email: %s", exc)


# ── Steele approval gate ──────────────────────────────────────────────────────

def request_steele_approval(lead_id: int) -> None:
    """
    Email Steele a preview link with Approve / Request Changes buttons.
    Called after build completes (by orchestrator or Stripe webhook).
    """
    lead = get_lead(lead_id)
    if not lead:
        log.error("request_steele_approval: lead #%d not found", lead_id)
        return

    approve_token = _create_token(lead_id, "approve")
    reject_token  = _create_token(lead_id, "reject")

    approve_url = f"{DASHBOARD_URL}/approve/{approve_token}"
    reject_url  = f"{DASHBOARD_URL}/reject/{reject_token}"
    preview_url = f"{DASHBOARD_URL}/preview/{lead_id}/"

    update_lead_status(lead_id, "build_ready", notes="Awaiting Steele approval")

    biz = lead.get("business_name", f"Lead #{lead_id}")
    subject = f"[Curbsite] Review & approve site build — {biz}"

    inner = (
        _p(f"<strong>{biz}</strong> is built and waiting for your approval.", size=17)
        + _btn(preview_url, "View the Built Site →")
        + _p("Happy with it? Approve to send the client their preview + payment link:")
        + _btn(approve_url, "✓ Approve & Send to Client", color=_BTN)
        + _p("Need changes first? Flag it for revision:")
        + _btn(reject_url, "✗ Request Changes", color=_BTN_RED)
        + _p(
            f"Lead #{lead_id} · {lead.get('niche', '')} · "
            f"{lead.get('city', '')}, {lead.get('state', '')}",
            size=13, color="#777",
        )
    )

    try:
        _send_html_email(STEELE_EMAIL, subject, _wrap(inner), (
            f"Site built for {biz}.\n\n"
            f"Preview: {preview_url}\n\n"
            f"Approve: {approve_url}\n\n"
            f"Request changes: {reject_url}"
        ))
        log.info("Steele approval email sent for lead #%d (%s)", lead_id, biz)
    except Exception as exc:
        log.error("Failed to send Steele approval email: %s", exc)


def approve_build(token: str) -> dict:
    """
    Process an approval token — send review-ready email to client.
    Returns {'ok': True, 'lead_id': int} or {'ok': False, 'reason': str}.
    """
    row = _use_token(token)
    if not row or row["action"] != "approve":
        return {"ok": False, "reason": "Invalid, expired, or already-used token."}

    lead_id = row["lead_id"]
    lead = get_lead(lead_id)
    if not lead:
        return {"ok": False, "reason": f"Lead #{lead_id} not found."}

    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET build_approved=1, updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), lead_id),
        )
    update_lead_status(lead_id, "build_ready", notes="Steele approved — awaiting client payment")

    preview_url = f"{DASHBOARD_URL}/preview/{lead_id}/"
    payment_url = lead.get("stripe_payment_url") or f"{PORTAL_URL}/pay/{lead_id}"

    notify_review_ready(lead, preview_url, payment_url)
    log.info("Build approved by Steele — review-ready email sent to client (lead #%d)", lead_id)
    return {"ok": True, "lead_id": lead_id}


def reject_build(token: str) -> dict:
    """
    Process a rejection token — flag lead as revision_needed.
    Returns {'ok': True, 'lead_id': int} or {'ok': False, 'reason': str}.
    """
    row = _use_token(token)
    if not row or row["action"] != "reject":
        return {"ok": False, "reason": "Invalid, expired, or already-used token."}

    lead_id = row["lead_id"]
    lead = get_lead(lead_id)
    if not lead:
        return {"ok": False, "reason": f"Lead #{lead_id} not found."}

    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET revision_needed=1, build_approved=0, updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), lead_id),
        )
    update_lead_status(lead_id, "building", notes="Revision requested by Steele")
    log.info("Build rejected by Steele — revision_needed set for lead #%d", lead_id)
    return {"ok": True, "lead_id": lead_id}
