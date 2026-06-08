"""
City rotation system for lead prospecting.

Cities are organized by state and population tier (1=largest) so high-value
markets are always scraped first while smaller cities cycle through over time.

Usage:
    from src.prospecting.locations import get_next_cities, mark_city_scraped
    cities = get_next_cities(n=6)  # list of dicts: {city, state, tier}
    # ... scrape ...
    mark_city_scraped("Indianapolis", "IN")
"""

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRAPED_JSON = _ROOT / "data" / "scraped_locations.json"

# tier 1 = largest (highest priority), tier 2 = medium, tier 3 = smaller
ALL_CITIES: list[dict] = [
    # ── Indiana (home state — most complete coverage) ─────────────────────────
    {"city": "Indianapolis",   "state": "IN", "tier": 1},
    {"city": "Fort Wayne",     "state": "IN", "tier": 1},
    {"city": "Evansville",     "state": "IN", "tier": 1},
    {"city": "South Bend",     "state": "IN", "tier": 1},
    {"city": "Carmel",         "state": "IN", "tier": 1},
    {"city": "Fishers",        "state": "IN", "tier": 1},
    {"city": "Bloomington",    "state": "IN", "tier": 1},
    {"city": "Hammond",        "state": "IN", "tier": 1},
    {"city": "Gary",           "state": "IN", "tier": 1},
    {"city": "Lafayette",      "state": "IN", "tier": 1},
    {"city": "Muncie",         "state": "IN", "tier": 2},
    {"city": "Terre Haute",    "state": "IN", "tier": 2},
    {"city": "Kokomo",         "state": "IN", "tier": 2},
    {"city": "Anderson",       "state": "IN", "tier": 2},
    {"city": "Noblesville",    "state": "IN", "tier": 2},
    {"city": "Greenwood",      "state": "IN", "tier": 2},
    {"city": "Elkhart",        "state": "IN", "tier": 2},
    {"city": "Mishawaka",      "state": "IN", "tier": 2},
    {"city": "Lawrence",       "state": "IN", "tier": 2},
    {"city": "Jeffersonville",  "state": "IN", "tier": 2},
    {"city": "Columbus",       "state": "IN", "tier": 2},
    {"city": "Portage",        "state": "IN", "tier": 2},
    {"city": "New Albany",     "state": "IN", "tier": 2},
    {"city": "Richmond",       "state": "IN", "tier": 2},
    {"city": "Westfield",      "state": "IN", "tier": 2},
    {"city": "Valparaiso",     "state": "IN", "tier": 2},
    {"city": "Goshen",         "state": "IN", "tier": 2},
    {"city": "Michigan City",  "state": "IN", "tier": 2},
    {"city": "West Lafayette", "state": "IN", "tier": 2},
    {"city": "Marion",         "state": "IN", "tier": 2},
    {"city": "Merrillville",   "state": "IN", "tier": 2},
    {"city": "Plainfield",     "state": "IN", "tier": 2},
    {"city": "Dyer",           "state": "IN", "tier": 3},
    {"city": "Schererville",   "state": "IN", "tier": 3},
    {"city": "Vincennes",      "state": "IN", "tier": 3},
    {"city": "Connersville",   "state": "IN", "tier": 3},
    {"city": "Frankfort",      "state": "IN", "tier": 3},
    {"city": "Shelbyville",    "state": "IN", "tier": 3},
    {"city": "Seymour",        "state": "IN", "tier": 3},
    {"city": "Bedford",        "state": "IN", "tier": 3},
    {"city": "Logansport",     "state": "IN", "tier": 3},
    {"city": "Peru",           "state": "IN", "tier": 3},
    {"city": "Wabash",         "state": "IN", "tier": 3},
    {"city": "Huntington",     "state": "IN", "tier": 3},
    {"city": "Decatur",        "state": "IN", "tier": 3},
    {"city": "Bluffton",       "state": "IN", "tier": 3},
    {"city": "Angola",         "state": "IN", "tier": 3},
    {"city": "Warsaw",         "state": "IN", "tier": 3},
    {"city": "Plymouth",       "state": "IN", "tier": 3},
    {"city": "Crawfordsville", "state": "IN", "tier": 3},
    {"city": "Greencastle",    "state": "IN", "tier": 3},
    {"city": "Martinsville",   "state": "IN", "tier": 3},
    {"city": "Linton",         "state": "IN", "tier": 3},
    {"city": "Jasper",         "state": "IN", "tier": 3},
    {"city": "Washington",     "state": "IN", "tier": 3},
    {"city": "Tell City",      "state": "IN", "tier": 3},
    {"city": "Princeton",      "state": "IN", "tier": 3},
    {"city": "Rushville",      "state": "IN", "tier": 3},
    {"city": "Hartford City",  "state": "IN", "tier": 3},
    # ── Illinois ─────────────────────────────────────────────────────────────
    {"city": "Chicago",            "state": "IL", "tier": 1},
    {"city": "Aurora",             "state": "IL", "tier": 1},
    {"city": "Joliet",             "state": "IL", "tier": 1},
    {"city": "Naperville",         "state": "IL", "tier": 1},
    {"city": "Rockford",           "state": "IL", "tier": 1},
    {"city": "Springfield",        "state": "IL", "tier": 1},
    {"city": "Elgin",              "state": "IL", "tier": 1},
    {"city": "Peoria",             "state": "IL", "tier": 1},
    {"city": "Champaign",          "state": "IL", "tier": 1},
    {"city": "Waukegan",           "state": "IL", "tier": 1},
    {"city": "Cicero",             "state": "IL", "tier": 2},
    {"city": "Bloomington",        "state": "IL", "tier": 2},
    {"city": "Arlington Heights",  "state": "IL", "tier": 2},
    {"city": "Evanston",           "state": "IL", "tier": 2},
    {"city": "Decatur",            "state": "IL", "tier": 2},
    {"city": "Schaumburg",         "state": "IL", "tier": 2},
    {"city": "Bolingbrook",        "state": "IL", "tier": 2},
    {"city": "Palatine",           "state": "IL", "tier": 2},
    {"city": "Skokie",             "state": "IL", "tier": 2},
    {"city": "Des Plaines",        "state": "IL", "tier": 2},
    {"city": "Orland Park",        "state": "IL", "tier": 2},
    {"city": "Tinley Park",        "state": "IL", "tier": 2},
    {"city": "Oak Lawn",           "state": "IL", "tier": 2},
    {"city": "Berwyn",             "state": "IL", "tier": 2},
    {"city": "Mount Prospect",     "state": "IL", "tier": 2},
    {"city": "Normal",             "state": "IL", "tier": 2},
    {"city": "Wheaton",            "state": "IL", "tier": 2},
    {"city": "Downers Grove",      "state": "IL", "tier": 2},
    {"city": "Hoffman Estates",    "state": "IL", "tier": 2},
    {"city": "Oak Park",           "state": "IL", "tier": 2},
    {"city": "Moline",             "state": "IL", "tier": 2},
    {"city": "Gurnee",             "state": "IL", "tier": 2},
    {"city": "Galesburg",          "state": "IL", "tier": 3},
    {"city": "Belleville",         "state": "IL", "tier": 3},
    {"city": "Carbondale",         "state": "IL", "tier": 3},
    {"city": "Quincy",             "state": "IL", "tier": 3},
    {"city": "Rock Island",        "state": "IL", "tier": 3},
    {"city": "East St. Louis",     "state": "IL", "tier": 3},
    {"city": "Calumet City",       "state": "IL", "tier": 3},
    {"city": "Pekin",              "state": "IL", "tier": 3},
    # ── Michigan ─────────────────────────────────────────────────────────────
    {"city": "Detroit",            "state": "MI", "tier": 1},
    {"city": "Grand Rapids",       "state": "MI", "tier": 1},
    {"city": "Warren",             "state": "MI", "tier": 1},
    {"city": "Sterling Heights",   "state": "MI", "tier": 1},
    {"city": "Ann Arbor",          "state": "MI", "tier": 1},
    {"city": "Lansing",            "state": "MI", "tier": 1},
    {"city": "Flint",              "state": "MI", "tier": 1},
    {"city": "Dearborn",           "state": "MI", "tier": 1},
    {"city": "Livonia",            "state": "MI", "tier": 1},
    {"city": "Westland",           "state": "MI", "tier": 1},
    {"city": "Kalamazoo",          "state": "MI", "tier": 1},
    {"city": "Waterford",          "state": "MI", "tier": 2},
    {"city": "Rochester Hills",    "state": "MI", "tier": 2},
    {"city": "Troy",               "state": "MI", "tier": 2},
    {"city": "Farmington Hills",   "state": "MI", "tier": 2},
    {"city": "Pontiac",            "state": "MI", "tier": 2},
    {"city": "Clinton Township",   "state": "MI", "tier": 2},
    {"city": "Southfield",         "state": "MI", "tier": 2},
    {"city": "Roseville",          "state": "MI", "tier": 2},
    {"city": "Dearborn Heights",   "state": "MI", "tier": 2},
    {"city": "Saginaw",            "state": "MI", "tier": 2},
    {"city": "Kentwood",           "state": "MI", "tier": 2},
    {"city": "East Lansing",       "state": "MI", "tier": 2},
    {"city": "Wyandotte",          "state": "MI", "tier": 2},
    {"city": "Midland",            "state": "MI", "tier": 2},
    {"city": "Muskegon",           "state": "MI", "tier": 2},
    {"city": "Holland",            "state": "MI", "tier": 2},
    {"city": "Traverse City",      "state": "MI", "tier": 2},
    {"city": "Jackson",            "state": "MI", "tier": 2},
    {"city": "Bay City",           "state": "MI", "tier": 2},
    {"city": "Battle Creek",       "state": "MI", "tier": 2},
    {"city": "Portage",            "state": "MI", "tier": 2},
    {"city": "Niles",              "state": "MI", "tier": 3},
    {"city": "Marquette",          "state": "MI", "tier": 3},
    {"city": "Escanaba",           "state": "MI", "tier": 3},
    {"city": "Alpena",             "state": "MI", "tier": 3},
    # ── Ohio ─────────────────────────────────────────────────────────────────
    {"city": "Columbus",           "state": "OH", "tier": 1},
    {"city": "Cleveland",          "state": "OH", "tier": 1},
    {"city": "Cincinnati",         "state": "OH", "tier": 1},
    {"city": "Toledo",             "state": "OH", "tier": 1},
    {"city": "Akron",              "state": "OH", "tier": 1},
    {"city": "Dayton",             "state": "OH", "tier": 1},
    {"city": "Parma",              "state": "OH", "tier": 1},
    {"city": "Canton",             "state": "OH", "tier": 1},
    {"city": "Youngstown",         "state": "OH", "tier": 1},
    {"city": "Lorain",             "state": "OH", "tier": 2},
    {"city": "Hamilton",           "state": "OH", "tier": 2},
    {"city": "Springfield",        "state": "OH", "tier": 2},
    {"city": "Kettering",          "state": "OH", "tier": 2},
    {"city": "Elyria",             "state": "OH", "tier": 2},
    {"city": "Lakewood",           "state": "OH", "tier": 2},
    {"city": "Cuyahoga Falls",     "state": "OH", "tier": 2},
    {"city": "Middletown",         "state": "OH", "tier": 2},
    {"city": "Euclid",             "state": "OH", "tier": 2},
    {"city": "Newark",             "state": "OH", "tier": 2},
    {"city": "Mansfield",          "state": "OH", "tier": 2},
    {"city": "Mentor",             "state": "OH", "tier": 2},
    {"city": "Cleveland Heights",  "state": "OH", "tier": 2},
    {"city": "Beavercreek",        "state": "OH", "tier": 2},
    {"city": "Strongsville",       "state": "OH", "tier": 2},
    {"city": "Fairfield",          "state": "OH", "tier": 2},
    {"city": "Dublin",             "state": "OH", "tier": 2},
    {"city": "Findlay",            "state": "OH", "tier": 2},
    {"city": "Warren",             "state": "OH", "tier": 2},
    {"city": "Lima",               "state": "OH", "tier": 2},
    {"city": "Westerville",        "state": "OH", "tier": 2},
    {"city": "Marion",             "state": "OH", "tier": 2},
    {"city": "Grove City",         "state": "OH", "tier": 2},
    {"city": "Brunswick",          "state": "OH", "tier": 2},
    {"city": "Stow",               "state": "OH", "tier": 2},
    {"city": "Medina",             "state": "OH", "tier": 2},
    {"city": "Lancaster",          "state": "OH", "tier": 2},
    {"city": "Gahanna",            "state": "OH", "tier": 2},
    {"city": "Huber Heights",      "state": "OH", "tier": 2},
    {"city": "Zanesville",         "state": "OH", "tier": 3},
    {"city": "Sandusky",           "state": "OH", "tier": 3},
    {"city": "Chillicothe",        "state": "OH", "tier": 3},
    {"city": "Riverside",          "state": "OH", "tier": 3},
    {"city": "Delaware",           "state": "OH", "tier": 3},
    {"city": "Marysville",         "state": "OH", "tier": 3},
    {"city": "Athens",             "state": "OH", "tier": 3},
    {"city": "Wooster",            "state": "OH", "tier": 3},
    {"city": "Ashland",            "state": "OH", "tier": 3},
    {"city": "Tiffin",             "state": "OH", "tier": 3},
    {"city": "Fremont",            "state": "OH", "tier": 3},
    {"city": "Defiance",           "state": "OH", "tier": 3},
    {"city": "Portsmouth",         "state": "OH", "tier": 3},
    {"city": "Ironton",            "state": "OH", "tier": 3},
    # ── Kentucky ─────────────────────────────────────────────────────────────
    {"city": "Louisville",         "state": "KY", "tier": 1},
    {"city": "Lexington",          "state": "KY", "tier": 1},
    {"city": "Bowling Green",      "state": "KY", "tier": 1},
    {"city": "Owensboro",          "state": "KY", "tier": 1},
    {"city": "Covington",          "state": "KY", "tier": 1},
    {"city": "Hopkinsville",       "state": "KY", "tier": 2},
    {"city": "Richmond",           "state": "KY", "tier": 2},
    {"city": "Florence",           "state": "KY", "tier": 2},
    {"city": "Georgetown",         "state": "KY", "tier": 2},
    {"city": "Henderson",          "state": "KY", "tier": 2},
    {"city": "Elizabethtown",      "state": "KY", "tier": 2},
    {"city": "Nicholasville",      "state": "KY", "tier": 2},
    {"city": "Jeffersontown",      "state": "KY", "tier": 2},
    {"city": "Frankfort",          "state": "KY", "tier": 2},
    {"city": "Paducah",            "state": "KY", "tier": 2},
    {"city": "Ashland",            "state": "KY", "tier": 2},
    {"city": "Radcliff",           "state": "KY", "tier": 2},
    {"city": "Madisonville",       "state": "KY", "tier": 2},
    {"city": "Murray",             "state": "KY", "tier": 2},
    {"city": "Winchester",         "state": "KY", "tier": 2},
    {"city": "Erlanger",           "state": "KY", "tier": 2},
    {"city": "St. Matthews",       "state": "KY", "tier": 2},
    {"city": "Danville",           "state": "KY", "tier": 3},
    {"city": "Independence",       "state": "KY", "tier": 3},
    {"city": "Shively",            "state": "KY", "tier": 3},
    {"city": "Glasgow",            "state": "KY", "tier": 3},
    {"city": "Lawrenceburg",       "state": "KY", "tier": 3},
    {"city": "Bardstown",          "state": "KY", "tier": 3},
    {"city": "Campbellsville",     "state": "KY", "tier": 3},
    {"city": "Shelbyville",        "state": "KY", "tier": 3},
    {"city": "Mount Sterling",     "state": "KY", "tier": 3},
    {"city": "London",             "state": "KY", "tier": 3},
    {"city": "Pikeville",          "state": "KY", "tier": 3},
    {"city": "Harlan",             "state": "KY", "tier": 3},
    {"city": "Corbin",             "state": "KY", "tier": 3},
    {"city": "Somerset",           "state": "KY", "tier": 3},
    {"city": "Middlesborough",     "state": "KY", "tier": 3},
    # ── Missouri (lower priority) ─────────────────────────────────────────────
    {"city": "Kansas City",        "state": "MO", "tier": 1},
    {"city": "St. Louis",          "state": "MO", "tier": 1},
    {"city": "Springfield",        "state": "MO", "tier": 1},
    {"city": "Columbia",           "state": "MO", "tier": 1},
    {"city": "Independence",       "state": "MO", "tier": 1},
    {"city": "Lee's Summit",       "state": "MO", "tier": 2},
    {"city": "O'Fallon",           "state": "MO", "tier": 2},
    {"city": "St. Joseph",         "state": "MO", "tier": 2},
    {"city": "St. Charles",        "state": "MO", "tier": 2},
    {"city": "Blue Springs",       "state": "MO", "tier": 2},
    {"city": "Joplin",             "state": "MO", "tier": 2},
    {"city": "Chesterfield",       "state": "MO", "tier": 2},
    {"city": "Jefferson City",     "state": "MO", "tier": 2},
    {"city": "Cape Girardeau",     "state": "MO", "tier": 2},
    {"city": "Florissant",         "state": "MO", "tier": 2},
    {"city": "Ballwin",            "state": "MO", "tier": 2},
    {"city": "Maryland Heights",   "state": "MO", "tier": 2},
    {"city": "Hazelwood",          "state": "MO", "tier": 2},
    {"city": "Kirkwood",           "state": "MO", "tier": 2},
    {"city": "Wentzville",         "state": "MO", "tier": 2},
]


def _load_scraped() -> dict:
    if _SCRAPED_JSON.exists():
        try:
            return json.loads(_SCRAPED_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_scraped(data: dict) -> None:
    _SCRAPED_JSON.parent.mkdir(parents=True, exist_ok=True)
    _SCRAPED_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_next_cities(n: int = 6) -> list[dict]:
    """
    Return up to n cities that haven't been scraped in the last 30 days.

    Selection strategy:
    - Filters out cities scraped within the past 30 days
    - Within each state, prioritizes tier-1 (largest) cities then oldest-scraped
    - Round-robins across states so every state gets coverage each cycle
    - Indiana is always first since it's the primary market
    """
    scraped = _load_scraped()
    cutoff = time.time() - (30 * 86400)

    per_state: dict[str, list] = {}
    for entry in ALL_CITIES:
        state = entry["state"]
        key = f"{entry['city']},{state}"
        last_scraped = scraped.get(key, 0)
        if last_scraped > cutoff:
            continue
        candidate = {**entry, "_last_scraped": last_scraped}
        per_state.setdefault(state, []).append(candidate)

    for state in per_state:
        per_state[state].sort(key=lambda x: (x["tier"], x["_last_scraped"]))

    # IN first as home market; MO last as lowest priority
    state_order = ["IN", "IL", "MI", "OH", "KY", "MO"]
    state_keys = [s for s in state_order if s in per_state]
    state_keys += [s for s in per_state if s not in state_keys]

    result = []
    while len(result) < n and any(per_state.get(s) for s in state_keys):
        for state in state_keys:
            if len(result) >= n:
                break
            bucket = per_state.get(state, [])
            if bucket:
                chosen = bucket.pop(0)
                chosen.pop("_last_scraped", None)
                result.append(chosen)

    log.info(
        "Selected %d cities for this run: %s",
        len(result),
        [(c["city"], c["state"]) for c in result],
    )
    return result


def mark_city_scraped(city: str, state: str) -> None:
    """Record that a city was scraped so it's skipped for 30 days."""
    data = _load_scraped()
    data[f"{city},{state}"] = time.time()
    _save_scraped(data)
    log.debug("Marked scraped: %s, %s", city, state)
