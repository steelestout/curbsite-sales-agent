"""
Go-live verification and client notification.

After deployment, this module:
1. Polls the live URL until it returns HTTP 200 (or times out)
2. Updates lead status to 'live'
3. Sends the client a "Your site is live!" email with:
   - Live URL
   - Portal login link (curbsite.co/portal)
   - Google Business Profile tip
   - Care plan upsell offer

DNS propagation can take 5–30 minutes. The poller retries for up to
10 minutes before giving up (Steele gets notified to check manually).
"""

import logging
import time
from typing import Optional

import requests

from src.config import (
    AGENCY_NAME, AGENCY_URL, AGENCY_OWNER, REPLY_TO,
    MODEL_DEFAULT,
)
from src.ai_client import chat
from src.crm.database import update_lead_status, log_outreach
from src.notifications.transactional import send_transactional
from src.outreach.pricing import PRICE_CARE_MIN, PRICE_CARE_MAX

log = logging.getLogger(__name__)

_POLL_INTERVAL_SECS = 30
_POLL_MAX_RETRIES = 20  # 10 minutes total


# ── Liveness check ────────────────────────────────────────────────────────────

def wait_for_live(domain: str, timeout_secs: int = 600) -> bool:
    """
    Poll https://{domain} until it returns HTTP 200 or timeout is reached.
    Returns True if the site came up, False if it timed out.
    """
    url = f"https://{domain}"
    retries = timeout_secs // _POLL_INTERVAL_SECS
    log.info("Waiting for %s to come live (up to %d min)...", url, timeout_secs // 60)

    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                log.info("Site is live: %s (after %d attempts)", url, attempt + 1)
                return True
            log.debug("Attempt %d: HTTP %d for %s", attempt + 1, resp.status_code, url)
        except requests.RequestException as exc:
            log.debug("Attempt %d: connection error for %s: %s", attempt + 1, url, exc)

        time.sleep(_POLL_INTERVAL_SECS)

    log.warning("Site did not come up within %d seconds: %s", timeout_secs, url)
    return False


# ── Go-live email ──────────────────────────────────────────────────────────────

_GOLIVE_SYSTEM = (
    "You are a friendly web developer letting a small business owner know their new website "
    "is live. Write a warm, celebratory email. Rules:\n"
    "- 4-6 sentences max\n"
    "- Mention the live URL prominently\n"
    "- Include one actionable next step (e.g., 'share it on your Facebook page')\n"
    "- Mention the monthly care plan naturally at the end\n"
    "- Sign off as {owner} from {agency}\n"
    "- Sound human, not like a bot\n"
    "Output format ONLY:\n"
    "SUBJECT: <subject>\n"
    "BODY:\n<body>"
).format(owner=AGENCY_OWNER, agency=AGENCY_NAME)


def _compose_golive_email(lead: dict, domain: str, portal_url: str) -> tuple[str, str]:
    business_name = lead.get("business_name", "your business")
    owner = lead.get("owner_name")
    greeting = f"Hi {owner}" if owner else "Hi there"
    live_url = f"https://{domain}"

    user = (
        f"Greeting: {greeting}\n"
        f"Business: {business_name}\n"
        f"Live URL: {live_url}\n"
        f"Portal: {portal_url}\n"
        f"Care plan: ${PRICE_CARE_MIN}–${PRICE_CARE_MAX}/mo (hosting, maintenance, updates)\n\n"
        "Write the go-live celebration email."
    )

    raw = chat(
        messages=[
            {"role": "system", "content": _GOLIVE_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=MODEL_DEFAULT,
        max_tokens=350,
        temperature=0.5,
        operation="golive_email",
        use_cache=False,
    )

    subject = f"🎉 {business_name} is live!"
    body = raw

    if "SUBJECT:" in raw and "BODY:" in raw:
        try:
            s_part, b_part = raw.split("BODY:", 1)
            subject = s_part.replace("SUBJECT:", "").strip().split("\n")[0].strip()
            body = b_part.strip()
        except ValueError:
            pass

    # Guarantee the live URL is in the body
    if live_url not in body:
        body += f"\n\nYour site: {live_url}"

    return subject, body


# ── Public API ────────────────────────────────────────────────────────────────

def notify_client_golive(
    lead: dict,
    domain: str,
    portal_url: str = "https://curbsite.co/portal",
    dry_run: bool = False,
) -> bool:
    """
    Send the go-live email to the client.
    Returns True if sent successfully.
    """
    client_email = lead.get("email")
    if not client_email:
        log.warning("No email for lead #%d — skipping go-live notification", lead["id"])
        return False

    subject, body = _compose_golive_email(lead, domain, portal_url)

    if dry_run:
        log.info("[DRY RUN] Would send go-live email to %s: %s", client_email, subject)
        return True

    # Go-live email is transactional — client has already paid and expects this.
    success = send_transactional(
        to_email=client_email,
        subject=subject,
        html=f"<div style='font-family:sans-serif;max-width:600px'>{body.replace(chr(10), '<br>')}</div>",
        text=body,
        lead_id=lead["id"],
        log_to_crm=True,
    )

    if success:
        log.info(
            "Go-live email sent to %s (%s) for %s",
            lead.get("business_name"), client_email, domain,
        )
    return success


def run_golive(
    lead: dict,
    domain: str,
    portal_url: str = "https://curbsite.co/portal",
    dry_run: bool = False,
    timeout_secs: int = 600,
) -> bool:
    """
    Full go-live sequence:
    1. Wait for site to become reachable
    2. Update lead status to 'live'
    3. Send client the go-live email

    Returns True if site came up and client was notified.
    """
    lead_id = lead["id"]

    if dry_run:
        log.info("[DRY RUN] Would poll https://%s and send go-live email to %s", domain, lead.get("email"))
        return True

    live = wait_for_live(domain, timeout_secs=timeout_secs)

    if not live:
        log.error(
            "Site did not come up for lead #%d (%s). "
            "Check VPS deployment and DNS manually.",
            lead_id, domain,
        )
        update_lead_status(
            lead_id, "deployed",
            notes=f"GOLIVE_TIMEOUT: {domain} did not respond after {timeout_secs}s",
        )
        return False

    update_lead_status(lead_id, "live", notes=f"domain={domain} | url=https://{domain}")
    log.info("Lead #%d is LIVE: https://%s", lead_id, domain)

    notify_client_golive(lead, domain, portal_url, dry_run=dry_run)
    return True
