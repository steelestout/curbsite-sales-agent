"""
Lead Dossier Generator — pre-call brief for Steele.

When a lead books a Calendly appointment (or reaches a score threshold),
this generates a clean markdown document covering everything Steele needs
to walk into the call prepared:

  - Business snapshot (niche, location, web presence)
  - Why they scored high (score reasons)
  - Recommended Curbsite tier + pricing
  - AI-generated conversation starters & likely objections
  - Quick research notes (pulled from scraper data)

Output: printed to terminal + saved as data/leads/<id>_<slug>_dossier.md
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import AGENCY_NAME, AGENCY_URL, AGENCY_OWNER, CACHE_DIR
from src.crm.database import get_lead
from src.outreach.pricing import recommend_tier, format_pricing_blurb, PRICE_CARE_MIN, PRICE_CARE_MAX
from src.outreach.calendly import booking_link
from src.ai_client import chat
from src.config import MODEL_DEFAULT

log = logging.getLogger(__name__)

DOSSIERS_DIR = Path("data/leads/dossiers")
DOSSIERS_DIR.mkdir(parents=True, exist_ok=True)


def _ai_conversation_prep(lead: dict, tier_rec) -> str:
    """
    Ask gpt-4o-mini to generate conversation starters + likely objections.
    Cached to disk.
    """
    system = (
        f"You are a sales coach for {AGENCY_NAME}, a web design agency. "
        "Given a lead's profile and the recommended package, produce a short "
        "pre-call brief. Output EXACTLY this structure:\n\n"
        "OPENERS:\n- <2–3 genuine opening questions to build rapport>\n\n"
        "LIKELY OBJECTIONS:\n- <3 most common objections this type of business raises, "
        "with a one-sentence response for each>\n\n"
        "CLOSING HOOK:\n<One sentence that closes toward booking or a next step>\n\n"
        "Keep it punchy. No fluff."
    )
    user = (
        f"Business: {lead.get('business_name')}\n"
        f"Niche: {lead.get('niche')}\n"
        f"City: {lead.get('city')}, {lead.get('state')}\n"
        f"Website quality: {lead.get('website_quality', 'none')}\n"
        f"Google rating: {lead.get('google_rating')} ({lead.get('review_count')} reviews)\n"
        f"Lead score: {lead.get('score')}\n"
        f"Recommended tier: {tier_rec.label} ({tier_rec.email_mention})\n"
        f"Pitch angle: {tier_rec.pitch_angle}\n"
    )
    return chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=MODEL_DEFAULT,
        max_tokens=400,
        temperature=0.4,
        operation="dossier_prep",
        use_cache=True,
    )


def generate_dossier(lead_id: int, save: bool = True) -> str:
    """
    Generate a markdown dossier for a lead. Returns the markdown string.
    """
    lead = get_lead(lead_id)
    if not lead:
        raise ValueError(f"Lead #{lead_id} not found in DB")

    tier_rec = recommend_tier(lead)
    score_reasons = []
    if lead.get("score_reasons"):
        try:
            score_reasons = json.loads(lead["score_reasons"])
        except (ValueError, TypeError):
            pass

    conv_prep = _ai_conversation_prep(lead, tier_rec)
    cal_link = booking_link(lead, campaign="dossier")

    # ── Build markdown ────────────────────────────────────────────────────────
    lines = [
        f"# Pre-Call Dossier — {lead['business_name']}",
        f"> Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC by {AGENCY_NAME} Sales Agent",
        "",
        "---",
        "",
        "## 📋 Business Snapshot",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Business** | {lead['business_name']} |",
        f"| **Niche** | {lead.get('niche', '—')} |",
        f"| **Location** | {lead.get('city', '—')}, {lead.get('state', '—')} |",
        f"| **Phone** | {lead.get('phone', '—')} |",
        f"| **Email** | {lead.get('email', '—')} |",
        f"| **Website** | {lead.get('website', 'None found')} |",
        f"| **Website quality** | {lead.get('website_quality', 'none').upper()} |",
        f"| **Google rating** | {lead.get('google_rating', '—')} ⭐ ({lead.get('review_count', 0)} reviews) |",
        f"| **Lead score** | **{lead.get('score', 0)} / 100** |",
        f"| **Status** | {lead.get('status', '—')} |",
        "",
        "---",
        "",
        "## 🎯 Why This Lead",
        "",
    ]

    for reason in score_reasons:
        lines.append(f"- {reason}")

    lines += [
        "",
        "---",
        "",
        "## 💰 Recommended Package",
        "",
        f"**{tier_rec.label}** | {tier_rec.email_mention}",
        "",
        tier_rec.pitch_angle,
        "",
        format_pricing_blurb(tier_rec, include_care=True),
        "",
        "> **Full pricing reference:**",
        f"> - Entry Tier: from $800 — 4-page site, mobile-first, GA4, click-to-call",
        f"> - Mid Tier: from $1,400 — + gallery, booking link, schema, on-page SEO",
        f"> - Top Tier: from $2,200 — + advanced SEO, landing page, 30-day support",
        f"> - Care Plan: ${PRICE_CARE_MIN}–${PRICE_CARE_MAX}/month (optional, cancel anytime)",
        "",
        "---",
        "",
        "## 🗣️ Conversation Prep",
        "",
        conv_prep,
        "",
        "---",
        "",
        "## 📅 Booking",
        "",
        f"Calendly link sent to prospect: [{cal_link}]({cal_link})",
        "",
        "---",
        "",
        "## 📝 Notes",
        "",
        lead.get("notes") or "_No notes yet._",
        "",
        "---",
        f"*{AGENCY_NAME} · {AGENCY_URL} · Agent auto-generated*",
    ]

    dossier = "\n".join(lines)

    if save:
        slug = (lead["business_name"] or "unknown").lower().replace(" ", "_")[:30]
        path = DOSSIERS_DIR / f"{lead_id}_{slug}_dossier.md"
        path.write_text(dossier, encoding="utf-8")
        log.info("Dossier saved: %s", path)

    return dossier


def generate_all_booked_dossiers() -> int:
    """
    Generate dossiers for all leads with status 'call_scheduled'.
    Returns count of dossiers generated.
    """
    from src.crm.database import get_leads
    leads = get_leads(status="call_scheduled", limit=50)
    count = 0
    for lead in leads:
        try:
            generate_dossier(lead["id"])
            count += 1
        except Exception as e:
            log.error("Failed dossier for lead #%d: %s", lead["id"], e)
    return count
