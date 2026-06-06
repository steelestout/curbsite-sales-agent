"""
Referral drip — warm referral email 30 days after go-live.

Each live client gets:
  Day 30  — Casual referral email with unique UTM-tagged link
  (one send only — not a full sequence)

CRM fields tracked:
  referral_link         — The unique UTM URL for this client
  referrals_sent        — Count of referral emails sent
  referrals_converted   — Count of clients who converted via this link

TODO: Decide referral incentive amount (Steele to set REFERRAL_INCENTIVE in .env)

Run daily via the scheduler:
  from src.referrals.drip import process_referral_drip
  process_referral_drip()
"""

import logging
from datetime import datetime

from src.config import AGENCY_NAME, AGENCY_URL, AGENCY_OWNER
from src.crm.database import get_conn
from src.notifications.client_status import _send_html_email

log = logging.getLogger(__name__)

# TODO: Steele to decide referral incentive (e.g. "$50 Amazon gift card", "one free month")
REFERRAL_INCENTIVE = "a special thank-you"


def _build_referral_link(lead_id: int) -> str:
    """Generate a unique UTM-tagged referral link for this client."""
    return f"{AGENCY_URL}?ref={lead_id}&utm_source=referral&utm_medium=client&utm_campaign=drip"


def _set_referral_link(lead_id: int, link: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET referral_link=?, updated_at=? WHERE id=?",
            (link, datetime.utcnow().isoformat(), lead_id),
        )


def _increment_referrals_sent(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET referrals_sent=COALESCE(referrals_sent,0)+1, updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), lead_id),
        )


def _referral_email_html(lead: dict, referral_link: str) -> tuple[str, str, str]:
    name = lead.get("owner_name") or lead.get("business_name", "there")
    first = name.split()[0]
    biz = lead.get("business_name", "your business")

    subject = f"Know anyone else who needs a website? (quick ask for {first})"
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
    <p style="font-size:17px;color:#1a1a1a;margin:0 0 18px;">Hey {first}!</p>

    <p style="font-size:16px;color:#333;line-height:1.6;margin:0 0 18px;">
      It's been about a month since {biz} launched — I hope you're seeing
      good things from the new site.
    </p>

    <p style="font-size:16px;color:#333;line-height:1.6;margin:0 0 18px;">
      Quick ask: do you know any other local business owners who could use
      a professional website? Restaurants, contractors, salons, photographers —
      anyone who's been putting it off.
    </p>

    <p style="font-size:16px;color:#333;line-height:1.6;margin:0 0 24px;">
      Just share your personal link below — if they sign up, I'll make sure
      you both get {REFERRAL_INCENTIVE}.
    </p>

    <div style="background:#f0f7f0;border-left:4px solid #2e7d32;padding:16px 20px;border-radius:0 8px 8px 0;margin:0 0 24px;">
      <p style="font-size:13px;color:#555;margin:0 0 6px;">Your referral link:</p>
      <a href="{referral_link}" style="color:#2e7d32;font-size:14px;word-break:break-all;">{referral_link}</a>
    </div>

    <a href="{referral_link}"
       style="display:block;background:#2e7d32;color:#ffffff;text-decoration:none;
              text-align:center;padding:18px 24px;border-radius:8px;font-size:18px;
              font-weight:bold;margin:0 0 24px;">
      Share My Referral Link
    </a>

    <p style="font-size:15px;color:#555;line-height:1.6;margin:0 0 12px;">
      No pressure at all — just a simple way to help someone you know get
      a site they'll be proud of.
    </p>

    <p style="font-size:15px;color:#555;">Thanks again,<br><strong>Steele @ Curbsite</strong></p>
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
        f"Hey {first}!\n\n"
        f"It's been about a month since {biz} launched — hope you're loving it.\n\n"
        f"Quick ask: know any other local business owners who need a website?\n\n"
        f"Share your referral link and if they sign up, you'll both get {REFERRAL_INCENTIVE}:\n"
        f"{referral_link}\n\n"
        f"Thanks,\nSteele @ Curbsite"
    )
    return subject, html, text


# ── Main processor ────────────────────────────────────────────────────────────

def process_referral_drip(dry_run: bool = False) -> dict:
    """
    Send referral email to clients 30+ days after go-live (once per client).
    Returns counts of emails sent.
    """
    now = datetime.utcnow()
    stats = {"sent": 0, "errors": 0}

    with get_conn() as conn:
        live_leads = conn.execute(
            "SELECT * FROM leads WHERE status='live' AND email IS NOT NULL"
        ).fetchall()

    for row in live_leads:
        lead = dict(row)
        lead_id = lead["id"]
        email = lead.get("email")

        # Skip if referral email already sent
        if lead.get("referrals_sent", 0) > 0:
            continue

        golive_at = lead.get("golive_at")
        if not golive_at:
            continue

        try:
            live_dt = datetime.fromisoformat(golive_at)
        except (ValueError, TypeError):
            continue

        days_live = (now - live_dt).days
        if days_live < 30:
            continue

        # Build or retrieve referral link
        referral_link = lead.get("referral_link") or _build_referral_link(lead_id)

        try:
            subject, html, text = _referral_email_html(lead, referral_link)
            if not dry_run:
                _send_html_email(email, subject, html, text)
                _set_referral_link(lead_id, referral_link)
                _increment_referrals_sent(lead_id)
            log.info("Referral email sent — lead #%d (%s)", lead_id, lead.get("business_name"))
            stats["sent"] += 1
        except Exception as exc:
            log.error("Referral drip failed for lead #%d: %s", lead_id, exc)
            stats["errors"] += 1

    return stats
