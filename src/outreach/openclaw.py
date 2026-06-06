"""
OpenClaw voice agent integration.

OFF BY DEFAULT — only activates when:
  1. OPENCLAW_ENABLED=true in .env
  2. Lead score >= SCORE_VOICE_THRESHOLD (default 85)

This keeps API costs minimal. Voice calls are expensive.
"""

import logging

import requests

from src.config import (
    OPENCLAW_ENABLED,
    OPENCLAW_API_KEY,
    OPENCLAW_AGENT_ID,
    SCORE_VOICE_THRESHOLD,
    AGENCY_NAME,
    AGENCY_OWNER,
    AGENCY_URL,
)
from src.crm.database import log_outreach, update_lead_status

log = logging.getLogger(__name__)

OPENCLAW_BASE_URL = "https://api.openclaw.io/v1"


def is_eligible(lead: dict) -> bool:
    """
    Returns True only if OpenClaw is enabled AND lead score meets threshold.
    """
    if not OPENCLAW_ENABLED:
        log.debug("OpenClaw disabled — skipping voice for lead #%s", lead.get("id"))
        return False
    if not OPENCLAW_API_KEY or not OPENCLAW_AGENT_ID:
        log.warning("OpenClaw enabled but API key / agent ID missing.")
        return False
    score = lead.get("score", 0)
    if score < SCORE_VOICE_THRESHOLD:
        log.debug(
            "Lead #%s score %d < threshold %d — no voice call",
            lead.get("id"),
            score,
            SCORE_VOICE_THRESHOLD,
        )
        return False
    return True


def trigger_call(lead: dict) -> bool:
    """
    Trigger an OpenClaw voice call for a qualified lead.
    Returns True on success.
    """
    if not is_eligible(lead):
        return False

    phone = lead.get("phone", "")
    if not phone:
        log.warning("Lead #%s has no phone — cannot call.", lead.get("id"))
        return False

    payload = {
        "agent_id": OPENCLAW_AGENT_ID,
        "to_number": phone,
        "metadata": {
            "business_name": lead.get("business_name"),
            "owner_name": lead.get("owner_name", ""),
            "niche": lead.get("niche"),
            "city": lead.get("city"),
            "agency_name": AGENCY_NAME,
            "agency_owner": AGENCY_OWNER,
            "agency_url": AGENCY_URL,
            "lead_score": lead.get("score"),
        },
    }

    try:
        resp = requests.post(
            f"{OPENCLAW_BASE_URL}/calls",
            json=payload,
            headers={
                "Authorization": f"Bearer {OPENCLAW_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        call_id = resp.json().get("call_id", "unknown")
        log.info(
            "OpenClaw call triggered for lead #%s (%s) — call_id=%s",
            lead.get("id"),
            lead.get("business_name"),
            call_id,
        )
        log_outreach(
            lead["id"],
            "call",
            subject=f"Voice call via OpenClaw — {call_id}",
            body=str(payload),
        )
        update_lead_status(lead["id"], "call_scheduled", notes=f"openclaw_call_id={call_id}")
        return True
    except requests.HTTPError as e:
        log.error("OpenClaw API error for lead #%s: %s", lead.get("id"), e)
        log_outreach(lead["id"], "call", error=str(e))
        return False
    except Exception as e:
        log.error("OpenClaw unexpected error: %s", e)
        return False
