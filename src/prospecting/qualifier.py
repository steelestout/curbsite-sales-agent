"""
Google PageSpeed Insights qualifier — augments lead scoring.

For leads that already have a website:
  - Fetches the PageSpeed Insights mobile performance score
  - Score < 50  → +20 to lead score (big opportunity)
  - Score 50-69 → +5  to lead score (some opportunity)
  - Results cached 7 days in the pagespeed_cache table

Requires GOOGLE_PAGESPEED_API_KEY in .env.
"""

import logging
from datetime import datetime, timedelta

import requests

from src.config import GOOGLE_PAGESPEED_API_KEY
from src.crm.database import get_conn

log = logging.getLogger(__name__)

_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_CACHE_DAYS = 7


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _get_cached(url: str) -> dict | None:
    cutoff = (datetime.utcnow() - timedelta(days=_CACHE_DAYS)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT mobile_score, desktop_score, cached_at FROM pagespeed_cache "
            "WHERE url=? AND cached_at > ?",
            (url, cutoff),
        ).fetchone()
    return dict(row) if row else None


def _save_cache(url: str, mobile: int, desktop: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pagespeed_cache (url, mobile_score, desktop_score)
               VALUES (?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 mobile_score  = excluded.mobile_score,
                 desktop_score = excluded.desktop_score,
                 cached_at     = datetime('now')""",
            (url, mobile, desktop),
        )


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_pagespeed(url: str) -> dict | None:
    """
    Return {'mobile_score': int, 'desktop_score': int} for a URL.
    Cached 7 days. Returns None if API key is missing or request fails.
    """
    if not GOOGLE_PAGESPEED_API_KEY:
        log.debug("GOOGLE_PAGESPEED_API_KEY not set — skipping PageSpeed check")
        return None

    cached = _get_cached(url)
    if cached:
        log.debug("PageSpeed cache hit: %s → mobile=%d", url, cached["mobile_score"])
        return {"mobile_score": cached["mobile_score"], "desktop_score": cached["desktop_score"]}

    scores: dict[str, int] = {}
    for strategy in ("mobile", "desktop"):
        try:
            resp = requests.get(
                _API_URL,
                params={
                    "url": url,
                    "strategy": strategy,
                    "key": GOOGLE_PAGESPEED_API_KEY,
                    "category": "performance",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            scores[strategy] = int(
                data["lighthouseResult"]["categories"]["performance"]["score"] * 100
            )
        except Exception as exc:
            log.warning("PageSpeed API error (%s, %s): %s", url, strategy, exc)
            return None

    if len(scores) == 2:
        _save_cache(url, scores["mobile"], scores["desktop"])
        log.info(
            "PageSpeed for %s — mobile: %d, desktop: %d",
            url, scores["mobile"], scores["desktop"],
        )
        return {"mobile_score": scores["mobile"], "desktop_score": scores["desktop"]}

    return None


def score_bonus_pagespeed(lead: dict) -> tuple[int, str]:
    """
    Return (bonus_points, reason_string) based on a lead's PageSpeed mobile score.
    Returns (0, '') if not applicable or API unavailable.
    """
    if not lead.get("has_website") or not lead.get("website"):
        return 0, ""

    result = fetch_pagespeed(lead["website"])
    if not result:
        return 0, ""

    mobile = result["mobile_score"]
    if mobile < 50:
        return 20, f"Slow mobile site (PageSpeed {mobile}/100) — major rebuild opportunity"
    if mobile < 70:
        return 5, f"Below-average mobile PageSpeed ({mobile}/100) — room to improve"
    return 0, ""
