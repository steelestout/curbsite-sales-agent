"""
Review request automation.

Timeline after go-live:
  Day 14  — Send review request email with direct Google review link
  Day 30  — One gentle reminder if no review received yet

CRM fields tracked:
  review_requested_at   — ISO timestamp of initial request
  review_reminder_sent  — ISO timestamp of reminder
  review_received       — 1 once review is confirmed

Run daily via the scheduler:
  from src.reviews.request import process_review_requests
  process_review_requests()
"""

import logging
from datetime import datetime, timedelta, timezone

from src.config import GOOGLE_REVIEW_URL, AGENCY_NAME, AGENCY_URL, AGENCY_OWNER
from src.crm.database import get_conn, get_leads
from src.notifications.client_status import _send_html_email

log = logging.getLogger(__name__)


# ── Email templates ───────────────────────────────────────────────────────────

def _review_request_html(lead: dict, review_url: str) -> tuple[str, str]:
    name = lead.get("owner_name") or lead.get("business_name", "there")
    first = name.split()[0]
    biz = lead.get("business_name", "your business")

    discount_note = ""
    if lead.get("care_plan"):
        discount_note = (
            "<p style='font-size:15px;color:#555;'>"
            "As a thank-you, we'll apply a <strong>10% discount</strong> on your next "
            "monthly care plan invoice when you leave a review."
            "</p>"
        )

    subject = f"Quick favor — would you leave {biz} a Google review?"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;">
<tr><td align="center" style="padding:24px 12px;">
<table width="100%" style="max-width:560px;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">

  <!-- Header -->
  <tr><td style="background:#1b3a1b;padding:24px;text-align:center;">
    <span style="color:#ffffff;font-size:20px;font-weight:bold;letter-spacing:1px;">CURBSITE</span>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:32px 28px;">
    <p style="font-size:17px;color:#1a1a1a;margin:0 0 18px;">Hey {first},</p>
    <p style="font-size:16px;color:#333;line-height:1.6;margin:0 0 18px;">
      It's been a couple weeks since {biz} launched — I hope you're loving the new site!
    </p>
    <p style="font-size:16px;color:#333;line-height:1.6;margin:0 0 24px;">
      Would you mind leaving us a quick Google review? It only takes about a minute
      and it makes a big difference for a small agency like ours.
    </p>

    {discount_note}

    <a href="{review_url}"
       style="display:block;background:#2e7d32;color:#ffffff;text-decoration:none;
              text-align:center;padding:18px 24px;border-radius:8px;font-size:18px;
              font-weight:bold;margin:24px 0;">
      Leave a Google Review ★
    </a>

    <p style="font-size:15px;color:#555;line-height:1.6;margin:0 0 12px;">
      Takes less than 60 seconds. Just tell others what it was like to work with us —
      no need to write an essay.
    </p>
    <p style="font-size:15px;color:#555;">Thank you so much,<br><strong>Steele @ Curbsite</strong></p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f0f0f0;padding:16px;text-align:center;">
    <p style="color:#999;font-size:12px;margin:0;">
      {AGENCY_NAME} · <a href="{AGENCY_URL}" style="color:#999;">{AGENCY_URL}</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    text = (
        f"Hey {first},\n\n"
        f"It's been a couple weeks since {biz} launched — hope you love the site!\n\n"
        f"Would you mind leaving a quick Google review? It only takes a minute.\n\n"
        f"{review_url}\n\n"
        f"{'As a thank-you, we will apply a 10% discount on your next monthly invoice.' if lead.get('care_plan') else ''}\n\n"
        f"Thank you,\nSteele @ Curbsite"
    )
    return subject, html, text


def _review_reminder_html(lead: dict, review_url: str) -> tuple[str, str, str]:
    name = lead.get("owner_name") or lead.get("business_name", "there")
    first = name.split()[0]
    biz = lead.get("business_name", "your business")

    subject = f"One last ask — Google review for {biz}?"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;">
<tr><td align="center" style="padding:24px 12px;">
<table width="100%" style="max-width:560px;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">

  <tr><td style="background:#1b3a1b;padding:24px;text-align:center;">
    <span style="color:#ffffff;font-size:20px;font-weight:bold;letter-spacing:1px;">CURBSITE</span>
  </td></tr>

  <tr><td style="padding:32px 28px;">
    <p style="font-size:17px;color:#1a1a1a;margin:0 0 18px;">Hey {first} — just a gentle nudge!</p>
    <p style="font-size:16px;color:#333;line-height:1.6;margin:0 0 24px;">
      I sent a review request a couple weeks back. No worries if you've been busy —
      this is the last I'll mention it. If you get 60 seconds, a Google review would
      mean a lot to us.
    </p>

    <a href="{review_url}"
       style="display:block;background:#2e7d32;color:#ffffff;text-decoration:none;
              text-align:center;padding:18px 24px;border-radius:8px;font-size:18px;
              font-weight:bold;margin:24px 0;">
      Leave a Google Review ★
    </a>

    <p style="font-size:15px;color:#555;">Thanks again for trusting us with {biz}.<br>
    <strong>Steele @ Curbsite</strong></p>
  </td></tr>

  <tr><td style="background:#f0f0f0;padding:16px;text-align:center;">
    <p style="color:#999;font-size:12px;margin:0;">
      {AGENCY_NAME} · <a href="{AGENCY_URL}" style="color:#999;">{AGENCY_URL}</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    text = (
        f"Hey {first} — one last nudge!\n\n"
        f"I sent a review request a couple weeks ago. If you get 60 seconds, "
        f"a Google review would mean a lot:\n\n{review_url}\n\n"
        f"Thanks for trusting us with {biz}.\nSteele @ Curbsite"
    )
    return subject, html, text


def _mark_review_requested(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET review_requested_at=?, updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), lead_id),
        )


def _mark_review_reminder(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET review_reminder_sent=?, updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), lead_id),
        )


# ── Main processor ────────────────────────────────────────────────────────────

def process_review_requests(dry_run: bool = False) -> dict:
    """
    Process pending review requests and reminders. Call daily.
    Returns counts of actions taken.
    """
    now = datetime.utcnow()
    stats = {"requests_sent": 0, "reminders_sent": 0, "errors": 0}

    review_url = GOOGLE_REVIEW_URL
    if not review_url:
        log.warning("GOOGLE_REVIEW_URL not set — skipping review requests")
        return stats

    with get_conn() as conn:
        live_leads = conn.execute(
            "SELECT * FROM leads WHERE status='live' AND email IS NOT NULL"
        ).fetchall()

    for row in live_leads:
        lead = dict(row)
        lead_id = lead["id"]
        email = lead.get("email")

        golive_at = lead.get("golive_at")
        if not golive_at:
            continue

        try:
            live_dt = datetime.fromisoformat(golive_at)
        except (ValueError, TypeError):
            continue

        days_live = (now - live_dt).days

        # 14-day initial request
        if days_live >= 14 and not lead.get("review_requested_at"):
            try:
                subject, html, text = _review_request_html(lead, review_url)
                if not dry_run:
                    _send_html_email(email, subject, html, text)
                    _mark_review_requested(lead_id)
                log.info("Review request sent — lead #%d (%s)", lead_id, lead.get("business_name"))
                stats["requests_sent"] += 1
            except Exception as exc:
                log.error("Review request failed for lead #%d: %s", lead_id, exc)
                stats["errors"] += 1

        # 30-day reminder (only if no review received and no reminder sent yet)
        elif (
            days_live >= 30
            and lead.get("review_requested_at")
            and not lead.get("review_reminder_sent")
            and not lead.get("review_received")
        ):
            try:
                subject, html, text = _review_reminder_html(lead, review_url)
                if not dry_run:
                    _send_html_email(email, subject, html, text)
                    _mark_review_reminder(lead_id)
                log.info("Review reminder sent — lead #%d (%s)", lead_id, lead.get("business_name"))
                stats["reminders_sent"] += 1
            except Exception as exc:
                log.error("Review reminder failed for lead #%d: %s", lead_id, exc)
                stats["errors"] += 1

    return stats
