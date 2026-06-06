"""
Lead scorer — assigns a 0–100 score to each lead and writes it back to the DB.

Scoring model (deterministic, no AI token cost):
  +30  no website at all
  +15  website quality is 'poor'
  +5   website quality is 'okay'
  +10  Google rating between 3.5–4.4 (solid business, not yet thriving online)
  +5   review count < 50 (small/growing business — high upside)
  +10  review count >= 50 (established, has budget)
  +10  niche is high-value (restaurant, dental, contractor)
  +5   niche is medium-value (salon, fitness, photography)
  +5   has a phone number (reachable)

AI enrichment (gpt-4o-mini, cached):
  Adds up to +10 based on short GPT reasoning about the opportunity.
"""

import json
import logging
from typing import Optional

from src.config import SCORE_VOICE_THRESHOLD
from src.crm.database import get_leads, upsert_lead
from src.ai_client import score_prompt

log = logging.getLogger(__name__)

HIGH_VALUE_NICHES = {"restaurant", "dental", "contractor", "plumber", "roofing", "hvac"}
MEDIUM_VALUE_NICHES = {"salon", "fitness", "photography", "bakery", "spa", "gym"}


def _base_score(lead: dict) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    wq = lead.get("website_quality", "none")
    hw = lead.get("has_website", 0)

    if not hw or wq == "none":
        score += 30
        reasons.append("No website — strong need")
    elif wq == "poor":
        score += 15
        reasons.append("Poor website — easy upgrade sell")
    elif wq == "okay":
        score += 5
        reasons.append("Okay website — room to improve")

    rating = lead.get("google_rating") or 0.0
    reviews = lead.get("review_count") or 0

    if 3.5 <= rating <= 4.4:
        score += 10
        reasons.append(f"Solid rating ({rating:.1f}) — established but room to grow online")
    elif rating > 4.4:
        score += 5
        reasons.append(f"High rating ({rating:.1f}) — good reputation to amplify")

    if reviews < 50:
        score += 5
        reasons.append(f"Low review count ({reviews}) — growing business")
    elif reviews >= 50:
        score += 10
        reasons.append(f"Good review count ({reviews}) — has budget")

    niche = (lead.get("niche") or "").lower()
    if niche in HIGH_VALUE_NICHES:
        score += 10
        reasons.append(f"High-value niche: {niche}")
    elif niche in MEDIUM_VALUE_NICHES:
        score += 5
        reasons.append(f"Medium-value niche: {niche}")

    if lead.get("phone"):
        score += 5
        reasons.append("Has phone — reachable")

    return min(score, 90), reasons  # cap base at 90, AI adds up to 10


def _ai_bonus(lead: dict) -> tuple[int, str]:
    """Ask gpt-4o-mini for a 0–10 bonus score. Cached to disk."""
    system = (
        "You are a sales intelligence assistant for Curbsite.co, a web design agency "
        "targeting small businesses. Given a lead's data, output a JSON object with two keys:\n"
        '  "bonus": integer 0-10 (how much extra opportunity this lead has)\n'
        '  "reason": one short sentence explaining the bonus.\n'
        "Be concise. Output ONLY valid JSON."
    )
    user = (
        f"Business: {lead.get('business_name')}\n"
        f"Niche: {lead.get('niche')}\n"
        f"City: {lead.get('city')}, {lead.get('state')}\n"
        f"Website quality: {lead.get('website_quality', 'none')}\n"
        f"Google rating: {lead.get('google_rating')}\n"
        f"Reviews: {lead.get('review_count')}\n"
    )
    try:
        raw = score_prompt(system, user)
        parsed = json.loads(raw)
        bonus = max(0, min(10, int(parsed.get("bonus", 0))))
        reason = parsed.get("reason", "")
        return bonus, reason
    except Exception as e:
        log.debug("AI bonus failed: %s", e)
        return 0, ""


def score_lead(lead: dict, use_ai: bool = True) -> int:
    """
    Score a single lead, update DB, return final score.
    """
    base, reasons = _base_score(lead)

    ai_bonus = 0
    ai_reason = ""
    if use_ai:
        ai_bonus, ai_reason = _ai_bonus(lead)
        if ai_reason:
            reasons.append(f"AI insight: {ai_reason}")

    # PageSpeed bonus — only for leads with an existing website
    ps_bonus, ps_reason = 0, ""
    if lead.get("has_website") and lead.get("website"):
        try:
            from src.prospecting.qualifier import score_bonus_pagespeed
            ps_bonus, ps_reason = score_bonus_pagespeed(lead)
            if ps_reason:
                reasons.append(ps_reason)
        except Exception as exc:
            log.debug("PageSpeed bonus skipped: %s", exc)

    final = min(100, base + ai_bonus + ps_bonus)

    upsert_lead({
        "business_name": lead["business_name"],
        "city": lead.get("city", ""),
        "score": final,
        "score_reasons": json.dumps(reasons),
        "status": lead.get("status", "new") if final < 40 else "scored",
    })

    log.info(
        "Scored %s: %d (base=%d, ai_bonus=%d)",
        lead["business_name"],
        final,
        base,
        ai_bonus,
    )

    # Flag high-score leads
    if final >= SCORE_VOICE_THRESHOLD:
        log.info("  ★ HIGH-SCORE LEAD — qualifies for voice outreach")

    return final


def score_all_new_leads(use_ai: bool = True) -> dict:
    """Score all 'new' leads in the DB. Returns summary stats."""
    leads = get_leads(status="new", limit=500)
    if not leads:
        log.info("No new leads to score.")
        return {"scored": 0, "high_value": 0}

    log.info("Scoring %d leads...", len(leads))
    scores = []
    for lead in leads:
        s = score_lead(lead, use_ai=use_ai)
        scores.append(s)

    high = sum(1 for s in scores if s >= SCORE_VOICE_THRESHOLD)
    return {
        "scored": len(scores),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "high_value": high,
    }
