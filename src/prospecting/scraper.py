"""
Lead scraper — pulls businesses from Yelp Fusion API and Google Places.

Strategy
────────
1. Search Yelp for each (niche, city) combination.
2. For each result, check if they have a website (or not).
3. Store raw lead data in the DB.
4. Scorer picks it up next.

Yelp Fusion API (free tier: 500 calls/day) is used first.
Falls back to a lightweight Google Maps scrape if no Yelp key.
"""

import json
import logging
import random
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.config import (
    TARGET_CITIES,
    TARGET_NICHES,
    PROSPECTING_DELAY,
)
from src.crm.database import upsert_lead
from src.prospecting.locations import get_next_cities, mark_city_scraped

log = logging.getLogger(__name__)

YELP_API_URL = "https://api.yelp.com/v3/businesses/search"
GOOGLE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


def _headers() -> dict:
    return {"User-Agent": random.choice(_USER_AGENTS)}


# ── Yelp ──────────────────────────────────────────────────────────────────────

def search_yelp(
    term: str,
    location: str,
    api_key: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Return raw Yelp business results."""
    resp = requests.get(
        YELP_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        params={
            "term": term,
            "location": location,
            "limit": limit,
            "offset": offset,
            "sort_by": "rating",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("businesses", [])


def yelp_to_lead(biz: dict, niche: str, city: str) -> dict:
    """Normalise a Yelp business dict to our lead schema."""
    location = biz.get("location", {})
    coords = biz.get("coordinates", {})
    return {
        "business_name": biz.get("name", ""),
        "phone": biz.get("phone", ""),
        "website": biz.get("url", ""),  # Yelp URL — not always their real site
        "niche": niche,
        "city": location.get("city", city),
        "state": location.get("state", ""),
        "google_rating": biz.get("rating"),
        "review_count": biz.get("review_count", 0),
        "has_website": 0,  # will be enriched by scorer
        "source": "yelp",
        "status": "new",
        "social_links": json.dumps({}),
    }


# ── Google Maps (no-key scrape) ───────────────────────────────────────────────

def scrape_google_maps(query: str, limit: int = 10) -> list[dict]:
    """
    Lightweight scrape of Google Maps search results.
    No API key needed. Returns minimal lead dicts.
    NOTE: Respects robots.txt spirit — only public listing data.
    """
    url = f"https://www.google.com/search?q={requests.utils.quote(query)}&tbm=lcl"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Google scrape failed for '%s': %s", query, e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []
    # Google Maps local pack — grab business names from structured data if available
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") in ("LocalBusiness", "Restaurant", "Store"):
                        results.append(_ld_to_lead(item))
            elif data.get("@type") in ("LocalBusiness", "Restaurant", "Store"):
                results.append(_ld_to_lead(data))
        except (json.JSONDecodeError, AttributeError):
            continue
        if len(results) >= limit:
            break
    return results


def _ld_to_lead(data: dict) -> dict:
    addr = data.get("address", {})
    return {
        "business_name": data.get("name", ""),
        "phone": data.get("telephone", ""),
        "website": data.get("url", ""),
        "city": addr.get("addressLocality", ""),
        "state": addr.get("addressRegion", ""),
        "niche": "",
        "has_website": 1 if data.get("url") else 0,
        "source": "google_scrape",
        "status": "new",
        "social_links": json.dumps({}),
        "score_reasons": json.dumps([]),
    }


# ── Website detection ─────────────────────────────────────────────────────────

def detect_website(business_name: str, city: str) -> Optional[str]:
    """
    Try to find a business's own website (not Yelp/Facebook).
    Uses a simple Google search.
    """
    query = f"{business_name} {city} official website"
    url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select("a[href]"):
            href = a["href"]
            if href.startswith("/url?q="):
                target = href.split("/url?q=")[1].split("&")[0]
                # Skip Yelp, Facebook, Google itself
                if not any(
                    skip in target
                    for skip in ["yelp.com", "facebook.com", "google.com", "instagram.com"]
                ):
                    return requests.utils.unquote(target)
    except Exception as e:
        log.debug("Website detection failed for %s: %s", business_name, e)
    return None


def check_website_quality(url: str) -> str:
    """
    Returns 'none' | 'poor' | 'okay' | 'good' based on simple heuristics.
    'poor' = loads but looks outdated / missing mobile meta / under 400 bytes content
    """
    if not url:
        return "none"
    try:
        resp = requests.get(url, headers=_headers(), timeout=10, allow_redirects=True)
        if resp.status_code >= 400:
            return "none"
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        score = 0
        if soup.find("meta", attrs={"name": "viewport"}):
            score += 2   # mobile-ready
        if len(html) > 10_000:
            score += 2   # substantial content
        if soup.find("script", src=lambda s: s and "analytics" in s.lower()):
            score += 1   # has analytics
        if soup.find("img"):
            score += 1   # has images

        if score >= 5:
            return "good"
        elif score >= 3:
            return "okay"
        else:
            return "poor"
    except Exception:
        return "none"


# ── Main prospecting run ──────────────────────────────────────────────────────

def prospect(
    yelp_api_key: Optional[str] = None,
    cities: Optional[list[str]] = None,
    niches: Optional[list[str]] = None,
    n_cities: int = 6,
) -> int:
    """
    Run a full prospecting pass. Returns number of leads upserted.

    When cities is None and TARGET_CITIES env var is not set, automatically
    selects cities using the 30-day rotation system across IN/IL/MI/OH/KY/MO.
    Pass cities=[...] or set TARGET_CITIES env var to override.
    """
    if cities is not None:
        city_entries = [{"city": c, "state": "", "tier": 2} for c in cities]
    elif TARGET_CITIES:
        city_entries = [{"city": c, "state": "", "tier": 2} for c in TARGET_CITIES]
    else:
        city_entries = get_next_cities(n=n_cities)

    niches = niches or TARGET_NICHES
    count = 0

    for entry in city_entries:
        city = entry["city"]
        state = entry.get("state", "")
        location = f"{city}, {state}" if state else city
        city_count = 0

        for niche in niches:
            log.info("Prospecting: %s in %s", niche, location)
            leads: list[dict] = []

            if yelp_api_key:
                try:
                    raw = search_yelp(niche, location, yelp_api_key)
                    leads = [yelp_to_lead(b, niche, city) for b in raw]
                    log.info("  Yelp: %d results", len(leads))
                except Exception as e:
                    log.warning("  Yelp failed: %s", e)
            else:
                google_leads = scrape_google_maps(f"{niche} in {location}")
                for lead in google_leads:
                    lead["niche"] = niche
                    lead["city"] = lead.get("city") or city
                    if state and not lead.get("state"):
                        lead["state"] = state
                leads = google_leads
                log.info("  Google scrape: %d results", len(leads))

            for lead in leads:
                if not lead.get("website") or "yelp.com" in (lead.get("website") or ""):
                    found = detect_website(lead["business_name"], lead.get("city", city))
                    if found:
                        lead["website"] = found
                        lead["has_website"] = 1

                if lead.get("website"):
                    lead["website_quality"] = check_website_quality(lead["website"])
                    lead["has_website"] = 1 if lead["website_quality"] != "none" else 0
                else:
                    lead["website_quality"] = "none"
                    lead["has_website"] = 0

                upsert_lead(lead)
                count += 1
                city_count += 1
                time.sleep(PROSPECTING_DELAY + random.uniform(0, 3))

        if state:
            mark_city_scraped(city, state)
        log.info("  City done: %s — %d leads", location, city_count)

    log.info("Prospecting complete — %d leads upserted", count)
    return count
