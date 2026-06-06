"""
Curbsite.co pricing tiers and pitch recommendation logic.

Pricing is pulled from .env so Steele can update without touching code.
Used by the email composer (to mention ballpark in outreach) and the
dossier generator (so Steele knows what to pitch on the call).

Tiers
─────
  Entry  — 4 pages, mobile-first, GA4, click-to-call, Maps, contact form
  Mid    — Everything in Entry + gallery, booking link, schema, SEO
  Top    — Everything in Mid + events page, landing page, advanced SEO,
            30-day support, 2 revision rounds
  Care   — Monthly maintenance add-on (any tier)
"""

import os
from dataclasses import dataclass
from typing import Optional

from src.config import TARGET_NICHES

# ── Load pricing from env (defaults reflect RDND as $800 Entry anchor) ────────
PRICE_ENTRY: int = int(os.getenv("PRICE_ENTRY", "800"))
PRICE_MID: int = int(os.getenv("PRICE_MID", "1400"))
PRICE_TOP: int = int(os.getenv("PRICE_TOP", "2200"))
PRICE_CARE_MIN: int = int(os.getenv("PRICE_CARE_MIN", "75"))
PRICE_CARE_MAX: int = int(os.getenv("PRICE_CARE_MAX", "125"))


@dataclass
class TierRecommendation:
    tier: str                    # 'entry' | 'mid' | 'top'
    price: int                   # exact starting price
    label: str                   # human-readable tier name
    headline_features: list[str] # 3 bullet points for email/dossier
    pitch_angle: str             # one-sentence why this tier fits THIS lead
    email_mention: str           # short phrase to drop in cold email


# Niches that tend to need more pages / features → Mid or Top
_MID_NICHES = {"restaurant", "salon", "spa", "gym", "fitness", "dental"}
_TOP_NICHES = {"contractor", "roofing", "plumber", "hvac", "lawyer", "medical"}


def recommend_tier(lead: dict) -> TierRecommendation:
    """
    Recommend a Curbsite tier based on the lead's niche, website quality,
    and review count. Returns a TierRecommendation dataclass.
    """
    niche = (lead.get("niche") or "").lower()
    wq = lead.get("website_quality", "none")
    reviews = lead.get("review_count") or 0
    score = lead.get("score", 0)

    # Top tier: established businesses in service niches with no/poor web
    if niche in _TOP_NICHES or (reviews >= 100 and wq in ("none", "poor") and score >= 70):
        return TierRecommendation(
            tier="top",
            price=PRICE_TOP,
            label="Top Tier",
            headline_features=[
                "Full multi-page site with dedicated landing page & events section",
                "Advanced local SEO (city + service targeting, Google Business optimization)",
                "30-day post-launch support + 2 revision rounds included",
            ],
            pitch_angle=(
                f"With {reviews} reviews and an established reputation, "
                f"{lead.get('business_name')} is ready for a site that matches its credibility."
            ),
            email_mention=f"starting around ${PRICE_TOP:,}",
        )

    # Mid tier: restaurants, salons, gyms — need gallery/booking/menu
    if niche in _MID_NICHES or (reviews >= 30 and wq in ("none", "poor")):
        return TierRecommendation(
            tier="mid",
            price=PRICE_MID,
            label="Mid Tier",
            headline_features=[
                "Full website with gallery, reviews section, and online booking/menu link",
                "LocalBusiness schema markup (helps rank in Google Maps)",
                "Basic on-page SEO + email capture popup",
            ],
            pitch_angle=(
                f"A {niche} like {lead.get('business_name')} benefits most from a site "
                f"with a gallery and a 'Book Now' button front and center."
            ),
            email_mention=f"starting around ${PRICE_MID:,}",
        )

    # Entry tier: small/new businesses, photographers, any low-complexity niche
    return TierRecommendation(
        tier="entry",
        price=PRICE_ENTRY,
        label="Entry Tier",
        headline_features=[
            "Clean 4-page site: Home, Services, About, Contact",
            "Mobile-first design, click-to-call, Google Maps embed, contact form",
            "Google Analytics 4 + SEO basics (sitemap, meta, robots.txt)",
        ],
        pitch_angle=(
            f"{lead.get('business_name')} needs a professional online home — "
            f"something that works on every phone and actually shows up in local search."
        ),
        email_mention=f"starting around ${PRICE_ENTRY:,}",
    )


def format_pricing_blurb(rec: TierRecommendation, include_care: bool = True) -> str:
    """Return a short paragraph suitable for email body or dossier."""
    lines = [
        f"**{rec.label}** — {rec.email_mention}",
        "",
        *[f"• {f}" for f in rec.headline_features],
    ]
    if include_care:
        lines += [
            "",
            f"• Optional monthly care plan: ${PRICE_CARE_MIN}–${PRICE_CARE_MAX}/month "
            f"(hosting, maintenance, content updates — cancel anytime)",
        ]
    return "\n".join(lines)
