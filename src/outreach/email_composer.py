"""
Email composer — generates personalised cold outreach emails using AI.

Templates
─────────
- no_website:  business has no website at all
- poor_website: business has an outdated/poor website
- generic:     fallback for anything else

Each template uses gpt-4o-mini (cheap) by default.
High-score leads (>= 75) get gpt-4o for final polish.
"""

import logging
from typing import Optional

from src.config import AGENCY_NAME, AGENCY_URL, AGENCY_OWNER, SCORE_VOICE_THRESHOLD
from src.ai_client import draft_email

log = logging.getLogger(__name__)

# ── System prompt (shared across templates) ───────────────────────────────────
_SYSTEM = f"""You are a friendly, sharp sales copywriter for {AGENCY_NAME} ({AGENCY_URL}), \
a web design agency. You write SHORT, natural cold outreach emails — NOT spam, NOT corporate fluff.

Rules:
- Subject line: under 10 words, curiosity-driven, no clickbait
- Body: 4–6 sentences max. No bullet lists. Conversational tone.
- One clear CTA: schedule a free 15-min call or reply to this email.
- Sign as {AGENCY_OWNER} from {AGENCY_NAME}.
- NEVER mention competitors by name.
- Output format: SUBJECT: <line>\nBODY:\n<body>
"""


def _build_user_prompt(
    business_name: str,
    owner_name: Optional[str],
    niche: str,
    city: str,
    website_quality: str,
    score_reasons: list[str],
) -> str:
    greeting = f"Hi {owner_name}" if owner_name else f"Hi there"
    reasons_summary = "; ".join(score_reasons[:3]) if score_reasons else ""

    if website_quality == "none":
        situation = f"{business_name} does not appear to have a website."
    elif website_quality == "poor":
        situation = f"{business_name} has a website but it looks outdated or isn't mobile-friendly."
    else:
        situation = f"{business_name} has a decent website but there may be room to grow online."

    return (
        f"Write a cold email to the owner of {business_name}, a {niche} in {city}.\n"
        f"Greeting: {greeting}\n"
        f"Situation: {situation}\n"
        f"Key insight: {reasons_summary}\n"
        f"Goal: get them on a free 15-min call or to reply with interest."
    )


def compose_outreach_email(lead: dict) -> tuple[str, str]:
    """
    Generate (subject, body) for a lead.
    Returns (subject, body) strings.
    """
    import json
    score = lead.get("score", 0)
    score_reasons = []
    if lead.get("score_reasons"):
        try:
            score_reasons = json.loads(lead["score_reasons"])
        except (ValueError, TypeError):
            pass

    high_quality = score >= 75  # use gpt-4o for top leads

    prompt = _build_user_prompt(
        business_name=lead.get("business_name", "your business"),
        owner_name=lead.get("owner_name"),
        niche=lead.get("niche", "business"),
        city=lead.get("city", "your area"),
        website_quality=lead.get("website_quality", "none"),
        score_reasons=score_reasons,
    )

    raw = draft_email(_SYSTEM, prompt, high_quality=high_quality)

    # Parse SUBJECT / BODY
    subject = ""
    body = raw
    if "SUBJECT:" in raw and "BODY:" in raw:
        parts = raw.split("BODY:", 1)
        subject_part = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()
        subject = subject_part.split("\n")[0].strip()
    elif "SUBJECT:" in raw:
        lines = raw.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("SUBJECT:"):
                subject = line.replace("SUBJECT:", "").strip()
                body = "\n".join(lines[i + 1:]).strip()
                break

    if not subject:
        subject = f"Quick question about {lead.get('business_name', 'your business')}'s online presence"

    return subject, body


def compose_followup_email(lead: dict, step: int) -> tuple[str, str]:
    """
    Generate a follow-up email (step 1 = first follow-up, step 2 = final nudge).
    """
    system = _SYSTEM + (
        "\nThis is a follow-up email. Reference that you emailed before. "
        "Keep it very short (2-3 sentences). Don't be pushy. Add value."
    )

    step_context = {
        1: "First follow-up, 3 days after initial email. Friendly check-in.",
        2: "Final follow-up, 7 days after initial. Low-pressure, leave the door open.",
    }.get(step, "Follow-up email.")

    user = (
        f"Write a follow-up email for {lead.get('business_name')}, "
        f"a {lead.get('niche')} in {lead.get('city')}.\n"
        f"Context: {step_context}"
    )

    raw = draft_email(system, user, high_quality=False)

    subject = ""
    body = raw
    if "SUBJECT:" in raw and "BODY:" in raw:
        parts = raw.split("BODY:", 1)
        subject = parts[0].replace("SUBJECT:", "").strip().split("\n")[0]
        body = parts[1].strip()

    if not subject:
        subject = f"Re: {lead.get('business_name', 'your business')}"

    return subject, body
