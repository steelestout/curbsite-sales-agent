"""
Calendly integration — generates trackable booking links for each lead.

No Calendly API key needed for basic link generation.
UTM parameters let you see in Calendly analytics which lead booked.

If CALENDLY_WEBHOOK_SECRET is set, the /webhook endpoint can receive
booking confirmations and auto-update lead status to 'call_scheduled'.

Usage
─────
  from src.outreach.calendly import booking_link, booking_cta

  link = booking_link(lead)   # https://calendly.com/you/15min?utm_source=...
  cta  = booking_cta(lead)    # "👉 Pick a time that works: <link>"
"""

import os
import hashlib
import hmac
import json
import logging
from urllib.parse import urlencode, urljoin

from src.config import AGENCY_OWNER

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CALENDLY_URL: str = os.getenv("CALENDLY_URL", "")
# e.g. https://calendly.com/steele-curbsite/15min
# Set this in .env — it's the direct link to your 15-minute intro event type.

CALENDLY_WEBHOOK_SECRET: str = os.getenv("CALENDLY_WEBHOOK_SECRET", "")


def booking_link(lead: dict, campaign: str = "cold_email") -> str:
    """
    Return a Calendly URL with UTM params tied to this specific lead.

    UTM params:
      utm_source   = curbsite_agent
      utm_medium   = email | followup_1 | followup_2
      utm_campaign = cold_email (default)
      utm_content  = lead_id-business_slug

    If CALENDLY_URL is not set, returns a placeholder with instructions.
    """
    if not CALENDLY_URL:
        log.warning("CALENDLY_URL not set in .env — using placeholder link")
        return "https://calendly.com/YOUR_LINK_HERE"

    slug = (lead.get("business_name") or "").lower().replace(" ", "-")[:30]
    lead_id = lead.get("id", "0")

    params = urlencode({
        "utm_source": "curbsite_agent",
        "utm_medium": campaign,
        "utm_content": f"{lead_id}-{slug}",
        "name": lead.get("owner_name") or lead.get("business_name") or "",
    })

    return f"{CALENDLY_URL.rstrip('/')}?{params}"


def booking_cta(lead: dict, campaign: str = "cold_email") -> str:
    """
    Return a ready-to-embed CTA string with the booking link.
    Suitable for dropping directly into an email body.
    """
    link = booking_link(lead, campaign=campaign)
    owner = lead.get("owner_name")
    if owner:
        return (
            f"If any of this sounds interesting, you can grab a free 15-minute slot "
            f"on my calendar here — no pressure, no pitch deck:\n{link}"
        )
    return (
        f"If you'd like to see what this could look like for your business, "
        f"here's a link to grab a free 15-minute call:\n{link}"
    )


def verify_webhook(payload: bytes, signature: str) -> bool:
    """
    Verify a Calendly webhook payload signature.
    Returns True if the signature matches.
    """
    if not CALENDLY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        CALENDLY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_booking_event(payload: dict) -> dict | None:
    """
    Parse a Calendly webhook payload for an 'invitee.created' event.
    Returns a dict with booking details, or None if not a booking event.
    """
    if payload.get("event") != "invitee.created":
        return None

    invitee = payload.get("payload", {}).get("invitee", {})
    questions = payload.get("payload", {}).get("questions_and_answers", [])

    # Try to extract UTM content = "lead_id-slug"
    tracking = payload.get("payload", {}).get("tracking", {})
    utm_content = tracking.get("utm_content", "")
    lead_id = None
    if utm_content and "-" in utm_content:
        try:
            lead_id = int(utm_content.split("-")[0])
        except ValueError:
            pass

    return {
        "lead_id": lead_id,
        "invitee_name": invitee.get("name"),
        "invitee_email": invitee.get("email"),
        "scheduled_at": payload.get("payload", {}).get("event", {}).get("start_time"),
        "calendly_event_uri": payload.get("payload", {}).get("event", {}).get("uri"),
    }
