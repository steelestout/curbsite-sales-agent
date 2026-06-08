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


# ── OpenStreetMap / Overpass (no-key scrape, replaces Google Maps) ────────────

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Map our niches to OSM tag filters (Overpass QL node filter syntax)
_NICHE_OSM_TAGS: dict[str, list[str]] = {
    "restaurant":  ['["amenity"="restaurant"]', '["amenity"="cafe"]', '["amenity"="fast_food"]'],
    "photography": ['["shop"="photography"]', '["craft"="photographer"]'],
    "salon":       ['["shop"="hairdresser"]', '["shop"="beauty"]', '["shop"="nail_salon"]'],
    "contractor":  ['["craft"~"builder|electrician|plumber|carpenter|roofer|hvac"]'],
    "fitness":     ['["leisure"~"fitness_centre|gym"]', '["amenity"="gym"]'],
    "dental":      ['["amenity"="dentist"]'],
    "auto":        ['["shop"~"car_repair|tyres|car"]'],
    "legal":       ['["office"="lawyer"]'],
    "real_estate": ['["office"="real_estate_agent"]'],
}


def _city_bbox(city: str, state: str) -> Optional[tuple[float, float, float, float]]:
    """Return (south, west, north, east) bounding box via Nominatim."""
    try:
        r = requests.get(
            _NOMINATIM_URL,
            params={"q": f"{city}, {state}, USA", "format": "json", "limit": 1},
            headers={"User-Agent": "curbsite-leads/1.0 (contact@curbsite.co)"},
            timeout=12,
        )
        results = r.json()
        if not results:
            log.warning("Nominatim: no result for %s, %s", city, state)
            return None
        bb = results[0]["boundingbox"]  # [south_lat, north_lat, west_lon, east_lon]
        return float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3])
    except Exception as e:
        log.warning("Nominatim failed for %s, %s: %s", city, state, e)
        return None


def search_overpass(niche: str, city: str, state: str, limit: int = 20) -> list[dict]:
    """
    Query OpenStreetMap via Overpass API for local businesses.
    Free, no API key. Returns lead dicts.
    Businesses with no website are valuable leads — they need our service.
    """
    bbox_tuple = _city_bbox(city, state)
    if not bbox_tuple:
        return []
    south, west, north, east = bbox_tuple
    bbox = f"{south},{west},{north},{east}"

    tag_filters = _NICHE_OSM_TAGS.get(niche.lower(), ['["amenity"="restaurant"]'])
    node_lines = "\n".join(f'  node{tf}["name"]({bbox});' for tf in tag_filters)
    query = f'[out:json][timeout:25];\n(\n{node_lines}\n);\nout {limit};'

    try:
        time.sleep(random.uniform(1, 2))  # respect Overpass rate limits
        resp = requests.get(
            _OVERPASS_URL,
            params={"data": query},
            headers={"User-Agent": "curbsite-leads/1.0 (contact@curbsite.co)"},
            timeout=35,
        )
        if resp.status_code != 200:
            log.warning("Overpass %d for %s in %s, %s", resp.status_code, niche, city, state)
            return []

        elements = resp.json().get("elements", [])
        results = []
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "").strip()
            if not name:
                continue
            website = tags.get("website") or tags.get("contact:website") or ""
            phone = tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile") or ""
            results.append({
                "business_name": name,
                "phone": phone,
                "website": website,
                "niche": niche,
                "city": tags.get("addr:city") or city,
                "state": tags.get("addr:state") or state,
                "has_website": 1 if website else 0,
                "source": "overpass",
                "status": "new",
                "social_links": json.dumps({}),
                "score_reasons": json.dumps([]),
            })
        log.info("  Overpass: %d results for %s in %s, %s", len(results), niche, city, state)
        return results
    except Exception as e:
        log.warning("Overpass failed for %s in %s, %s: %s", niche, city, state, e)
        return []


# ── Website detection ─────────────────────────────────────────────────────────

def detect_website(business_name: str, city: str) -> Optional[str]:
    """
    Try to find a business's own website via DuckDuckGo HTML search.
    Google blocks VPS IPs; DuckDuckGo is more permissive.
    """
    query = f"{business_name} {city} official website"
    url = f"https://duckduckgo.com/html/?q={requests.utils.quote(query)}"
    _SKIP = ("yelp.com", "facebook.com", "google.com", "instagram.com",
             "yellowpages.com", "bbb.org", "tripadvisor.com")
    try:
        resp = requests.get(url, headers=_headers(), timeout=12)
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select("a.result__url, a[href*='uddg=']"):
            href = a.get("href", "")
            if "uddg=" in href:
                href = requests.utils.unquote(href.split("uddg=")[1].split("&")[0])
            if href.startswith("http") and not any(s in href for s in _SKIP):
                return href
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
                leads = search_overpass(niche, city, state or "IN")

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
