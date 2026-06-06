"""
Curbsite.co pricing tiers — exact data scraped from curbsite/components/landing/Pricing.tsx.

Pricing is by BUSINESS TYPE, not a single global tier.
Default pitch = Mid tier (anchored there per Steele's sales strategy).
Entry = fallback/last resort. Top = upsell for established/competitive prospects.

Payment methods (all automated touchpoints): Stripe (portal), Venmo, CashApp.
DO NOT mention Zelle or check in any automated outreach.

Special offer: First 5 founding clients get a FREE full build in exchange for
a Google/Facebook review and portfolio feature permission.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

# ── Founding client offer ──────────────────────────────────────────────────────
FOUNDING_CLIENTS_TOTAL: int = 5
FOUNDING_CLIENTS_REMAINING: int = int(os.getenv("FOUNDING_CLIENTS_REMAINING", "5"))

# ── Per-niche pricing tables ──────────────────────────────────────────────────
# Source: curbsite/components/landing/Pricing.tsx (live site)

PRICING: dict[str, list[dict]] = {
    "restaurant": [
        {
            "tier": "entry", "name": "Menu",
            "headline": "Get found. Get visits.",
            "price": 800, "care": 75,
            "tagline": "Everything a local restaurant needs to show up online and bring customers through the door.",
            "features": ["5-page mobile-first site", "Menu page + hours & map",
                         "Contact form + social links", "Google Business setup", "SSL included"],
        },
        {
            "tier": "mid", "name": "Entrée",
            "headline": "Take orders online.",
            "price": 1800, "care": 100, "popular": True,
            "tagline": "Add online ordering, reservations, and the SEO to make sure hungry customers find you first.",
            "features": ["Everything in Menu", "Online ordering (Square / Toast)",
                         "Photo gallery", "Reservation / waitlist link",
                         "Reviews section", "Basic SEO + 1 revision"],
        },
        {
            "tier": "top", "name": "Chef's Table",
            "headline": "Own your market.",
            "price": 3200, "care": 125,
            "tagline": "Full custom branding, loyalty tools, gift cards, and local SEO that dominates your area.",
            "features": ["Everything in Entrée", "Custom branded design",
                         "Loyalty & email capture", "Events & specials page",
                         "Gift cards integration", "Full local SEO + analytics",
                         "2 revision rounds"],
        },
    ],
    "cafe": [  # alias → restaurant pricing
        {"tier": "entry", "name": "Menu",        "price": 800,  "care": 75},
        {"tier": "mid",   "name": "Entrée",       "price": 1800, "care": 100, "popular": True},
        {"tier": "top",   "name": "Chef's Table", "price": 3200, "care": 125},
    ],
    "salon": [
        {
            "tier": "entry", "name": "The Basics",
            "headline": "Open for business online.",
            "price": 700, "care": 75,
            "tagline": "A clean, professional site that shows your services and makes it easy for clients to reach you.",
            "features": ["4–5 page mobile-first site", "Services + prices list",
                         "Hours, map, click-to-call", "Social links",
                         "Google Business setup + SSL"],
        },
        {
            "tier": "mid", "name": "The Chair",
            "headline": "Book while you sleep.",
            "price": 1500, "care": 100, "popular": True,
            "tagline": "Online booking integration so clients can schedule 24/7. Your chair stays full, you stay focused.",
            "features": ["Everything in The Basics",
                         "Online booking (Square / Booksy / Vagaro)",
                         "Cut & style photo gallery", "Reviews section",
                         "Basic SEO + 1 revision"],
        },
        {
            "tier": "top", "name": "The Suite",
            "headline": "A brand, not just a site.",
            "price": 2600, "care": 125,
            "tagline": "Custom branding, staff profiles, loyalty capture, and gift cards — for the shop that's going places.",
            "features": ["Everything in The Chair", "Custom branding",
                         "Staff & stylist profiles", "Loyalty & email capture",
                         "Gift cards", "Full local SEO + analytics", "2 revision rounds"],
        },
    ],
    "barber": [  # alias → salon pricing
        {"tier": "entry", "name": "The Basics", "price": 700,  "care": 75},
        {"tier": "mid",   "name": "The Chair",  "price": 1500, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Suite",  "price": 2600, "care": 125},
    ],
    "nail": [  # alias → salon pricing
        {"tier": "entry", "name": "The Basics", "price": 700,  "care": 75},
        {"tier": "mid",   "name": "The Chair",  "price": 1500, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Suite",  "price": 2600, "care": 125},
    ],
    "auto": [
        {
            "tier": "entry", "name": "Tune-Up",
            "headline": "Show up when they search.",
            "price": 700, "care": 75,
            "tagline": "A fast, clear site with your services, location, and a phone number they can tap in one second.",
            "features": ["4–5 page mobile-first site", "Services list",
                         "Hours, map, click-to-call", "Google Business setup + SSL"],
        },
        {
            "tier": "mid", "name": "The Shop",
            "headline": "Turn searches into appointments.",
            "price": 1600, "care": 100, "popular": True,
            "tagline": "Add appointment booking, a quote form, and reviews so customers choose you before calling anyone else.",
            "features": ["Everything in Tune-Up",
                         "Appointment / quote request form",
                         "Reviews section + photo gallery",
                         "Financing & warranty info page",
                         "Basic SEO + 1 revision"],
        },
        {
            "tier": "top", "name": "Full Service",
            "headline": "The complete package.",
            "price": 2800, "care": 125,
            "tagline": "Custom branding, fleet/commercial pages, full local SEO, and coupons — for the shop that wants to grow.",
            "features": ["Everything in The Shop", "Custom branding",
                         "Fleet & commercial page", "Coupons & specials section",
                         "Full local SEO + analytics", "2 revision rounds"],
        },
    ],
    "tire": [  # alias → auto pricing
        {"tier": "entry", "name": "Tune-Up",     "price": 700,  "care": 75},
        {"tier": "mid",   "name": "The Shop",    "price": 1600, "care": 100, "popular": True},
        {"tier": "top",   "name": "Full Service","price": 2800, "care": 125},
    ],
    "contractor": [
        {
            "tier": "entry", "name": "Groundwork",
            "headline": "Plant your flag online.",
            "price": 800, "care": 75,
            "tagline": "A clean site with your services, service area, and a contact form so local homeowners can find you.",
            "features": ["5-page mobile-first site", "Services + service-area map",
                         "Click-to-call + contact form", "Google Business setup + SSL"],
        },
        {
            "tier": "mid", "name": "The Build",
            "headline": "Let your work do the selling.",
            "price": 1900, "care": 100, "popular": True,
            "tagline": "Before/after gallery, quote request form, and testimonials — the portfolio that wins jobs before you even pick up the phone.",
            "features": ["Everything in Groundwork",
                         "Before & after photo gallery",
                         "Quote-request form",
                         "Reviews & testimonials section",
                         "Basic SEO + 1 revision"],
        },
        {
            "tier": "top", "name": "The Estate",
            "headline": "Dominate your service area.",
            "price": 3200, "care": 125,
            "tagline": "Custom branding, full project portfolio, seasonal services, and local SEO that keeps the phone ringing year-round.",
            "features": ["Everything in The Build", "Custom branding",
                         "Full project portfolio pages", "Seasonal services section",
                         "Full local SEO + analytics", "2 revision rounds"],
        },
    ],
    "landscaping": [  # alias → contractor pricing
        {"tier": "entry", "name": "Groundwork", "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Build",  "price": 1900, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Estate", "price": 3200, "care": 125},
    ],
    "lawn": [
        {"tier": "entry", "name": "Groundwork", "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Build",  "price": 1900, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Estate", "price": 3200, "care": 125},
    ],
    "roofing": [
        {"tier": "entry", "name": "Groundwork", "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Build",  "price": 1900, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Estate", "price": 3200, "care": 125},
    ],
    "plumber": [
        {"tier": "entry", "name": "Groundwork", "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Build",  "price": 1900, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Estate", "price": 3200, "care": 125},
    ],
    "hvac": [
        {"tier": "entry", "name": "Groundwork", "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Build",  "price": 1900, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Estate", "price": 3200, "care": 125},
    ],
    "fitness": [
        {
            "tier": "entry", "name": "Warm-Up",
            "headline": "Get discovered locally.",
            "price": 800, "care": 75,
            "tagline": "A professional site that shows what you offer, where you are, and how new clients can reach you.",
            "features": ["5-page mobile-first site", "Services, hours & map",
                         "Click-to-call + contact form", "Google Business setup + SSL"],
        },
        {
            "tier": "mid", "name": "The Membership",
            "headline": "Fill your schedule.",
            "price": 1900, "care": 100, "popular": True,
            "tagline": "Class schedule, online booking, and a new-client intro page that converts first-time visitors into regulars.",
            "features": ["Everything in Warm-Up",
                         "Class schedule or appointment booking",
                         "New-client intro offer page",
                         "Photo gallery + reviews",
                         "Basic SEO + 1 revision"],
        },
        {
            "tier": "top", "name": "The Program",
            "headline": "Build a brand that grows.",
            "price": 3200, "care": 125,
            "tagline": "Custom design, staff profiles, email capture for offers, and the full SEO stack for a studio that's serious about growing.",
            "features": ["Everything in The Membership", "Custom branding",
                         "Staff & trainer profiles", "Email capture for offers",
                         "Full local SEO + analytics", "2 revision rounds"],
        },
    ],
    "gym": [
        {"tier": "entry", "name": "Warm-Up",       "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Membership", "price": 1900, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Program",    "price": 3200, "care": 125},
    ],
    "dental": [  # Default to contractor-style pricing for medical/health
        {"tier": "entry", "name": "Essentials", "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Practice","price": 1900, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Clinic",  "price": 3200, "care": 125},
    ],
    "photography": [  # Entry-leaning niche (RDND is $800)
        {"tier": "entry", "name": "The Portfolio", "price": 800,  "care": 75},
        {"tier": "mid",   "name": "The Studio",    "price": 1500, "care": 100, "popular": True},
        {"tier": "top",   "name": "The Agency",    "price": 2600, "care": 125},
    ],
    "default": [  # Fallback for unlisted niches
        {"tier": "entry", "name": "Entry",  "price": 800,  "care": 75},
        {"tier": "mid",   "name": "Mid",    "price": 1800, "care": 100, "popular": True},
        {"tier": "top",   "name": "Top",    "price": 3200, "care": 125},
    ],
}

# ── Universal features (every tier, every niche) ───────────────────────────────
UNIVERSAL_FEATURES = [
    "Custom design, no templates",
    "Mobile-first & fully responsive",
    "Google Business profile setup",
    "SSL certificate",
    "Click-to-call + contact form",
    "Hours, location & map",
    "Social media links",
    "Free mockup before payment",
]

# ── Payment methods (use in ALL automated outreach) ───────────────────────────
PAYMENT_METHODS = "Stripe (via our secure portal), Venmo, or CashApp"
# NOTE: Check is in-person only — never mention in automated email/scripts.
# Zelle is not accepted.


@dataclass
class TierRecommendation:
    tier: str                       # 'entry' | 'mid' | 'top'
    price: int
    care: int
    label: str                      # tier display name (e.g. "Entrée", "The Chair")
    headline: str
    headline_features: list[str]    # 3 key features for email/script
    pitch_angle: str
    email_mention: str              # short phrase for email body
    upsell_seed: str                # plant this if downgraded from mid → entry
    niche_category: str             # resolved niche key


def _niche_key(niche: str) -> str:
    """Resolve a raw niche string to a PRICING key."""
    niche_lower = (niche or "").lower()
    for key in PRICING:
        if key in niche_lower or niche_lower in key:
            return key
    return "default"


def _get_tier(niche_key: str, tier: str) -> dict:
    tiers = PRICING.get(niche_key, PRICING["default"])
    for t in tiers:
        if t["tier"] == tier:
            return t
    return tiers[1]  # fallback to mid


def _top_tier_signals(lead: dict) -> bool:
    """Return True if the lead shows signals of being a top-tier candidate."""
    signals = [
        lead.get("review_count", 0) >= 80,
        lead.get("website_quality") in ("okay", "good"),  # already has presence
        lead.get("score", 0) >= 75,
        (lead.get("niche") or "").lower() in ("contractor", "roofing", "hvac", "plumber", "dental", "lawyer"),
    ]
    return sum(signals) >= 2


def recommend_tier(lead: dict) -> TierRecommendation:
    """
    Recommend a Curbsite tier for a lead.

    Strategy (per Steele's sales rules):
    1. DEFAULT: Mid tier — this is what Rook and emails anchor to first.
    2. UPSELL: Top tier if lead shows 2+ established-business signals.
    3. FALLBACK: Entry only if prospect pushes back hard on mid price.

    Never open with Entry tier pricing.
    """
    niche = lead.get("niche", "")
    niche_key = _niche_key(niche)
    reviews = lead.get("review_count") or 0
    score = lead.get("score", 0)
    wq = lead.get("website_quality", "none")
    city = lead.get("city", "your area")
    business_name = lead.get("business_name", "your business")

    # Top tier: established, competitive, or asking for more
    if _top_tier_signals(lead):
        t = _get_tier(niche_key, "top")
        return TierRecommendation(
            tier="top",
            price=t["price"],
            care=t.get("care", 125),
            label=t.get("name", "Top Tier"),
            headline=t.get("headline", "Own your market."),
            headline_features=t.get("features", UNIVERSAL_FEATURES)[:3],
            pitch_angle=(
                f"With {reviews} reviews and an established reputation, "
                f"{business_name} is ready for a site that dominates {city} search results."
            ),
            email_mention=f"around ${t['price']:,}",
            upsell_seed="",
            niche_category=niche_key,
        )

    # Mid tier: default for everyone
    t = _get_tier(niche_key, "mid")
    return TierRecommendation(
        tier="mid",
        price=t["price"],
        care=t.get("care", 100),
        label=t.get("name", "Mid Tier"),
        headline=t.get("headline", "More than just a site."),
        headline_features=t.get("features", UNIVERSAL_FEATURES)[:3],
        pitch_angle=(
            f"The most popular package for {niche or 'businesses'} in {city} — "
            f"gives you {t.get('headline', 'everything you need to grow online')}."
        ),
        email_mention=f"around ${t['price']:,}",
        upsell_seed=(
            f"If budget is a concern, we do have a smaller entry-level package starting at "
            f"${_get_tier(niche_key, 'entry')['price']:,} — but most clients end up moving to "
            f"the {t.get('name', 'mid')} within the first few months once they see the results."
        ),
        niche_category=niche_key,
    )


def entry_tier(lead: dict) -> TierRecommendation:
    """
    Return the entry tier recommendation.
    Used ONLY when a prospect explicitly pushes back on mid-tier pricing.
    Always includes the upsell_seed to plant the upgrade.
    """
    niche = lead.get("niche", "")
    niche_key = _niche_key(niche)
    t = _get_tier(niche_key, "entry")
    mid = _get_tier(niche_key, "mid")
    business_name = lead.get("business_name", "your business")

    return TierRecommendation(
        tier="entry",
        price=t["price"],
        care=t.get("care", 75),
        label=t.get("name", "Entry Tier"),
        headline=t.get("headline", "Get found online."),
        headline_features=t.get("features", UNIVERSAL_FEATURES)[:3],
        pitch_angle=f"{business_name} needs a professional online home — fast, mobile, visible in local search.",
        email_mention=f"starting at ${t['price']:,}",
        upsell_seed=(
            f"This is the lean version — most clients upgrade to {mid.get('name', 'the mid package')} "
            f"(${mid['price']:,}) once they start seeing the traffic it drives."
        ),
        niche_category=niche_key,
    )


def format_pricing_blurb(rec: TierRecommendation, include_care: bool = True) -> str:
    lines = [
        f"**{rec.label}** — {rec.email_mention}",
        "",
        *[f"• {f}" for f in rec.headline_features],
    ]
    if include_care:
        lines += [
            "",
            f"• Optional care plan: ${rec.care}/mo — hosting, maintenance, updates (cancel anytime)",
        ]
    return "\n".join(lines)


def get_all_prices_for_niche(niche: str) -> list[dict]:
    """Return the full tier list for a niche (for Rook's training context)."""
    return PRICING.get(_niche_key(niche), PRICING["default"])
