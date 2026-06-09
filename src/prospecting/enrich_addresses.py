#!/usr/bin/env python3
"""
Address enrichment for Curbsite leads DB.
Prefers Nominatim reverse geocoding (lat/lon) when columns exist;
falls back to forward geocoding (business_name + city + state).
"""

import sqlite3
import time
import json
import urllib.request
import urllib.parse

DB_PATH = '/opt/curbsite-sales-agent/data/leads/leads.db'
NOMINATIM_BASE = 'https://nominatim.openstreetmap.org'
USER_AGENT = 'CurbsiteBot/1.0 steele@getcurbsite.co'
BATCH_LIMIT = 200
RATE_LIMIT = 1.0  # Nominatim ToS: max 1 req/sec

STATE_ABBREV = {
    "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
    "Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA",
    "Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA",
    "Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD",
    "Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS",
    "Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH",
    "New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC",
    "North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA",
    "Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN",
    "Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA",
    "West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY",
}


def nominatim_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"    HTTP error: {e}")
        return None


def parse_address(addr):
    house = addr.get('house_number', '').strip()
    road = addr.get('road', '').strip()
    address_line1 = f"{house} {road}".strip() if house else road
    city = (addr.get('city') or addr.get('town') or addr.get('village')
            or addr.get('hamlet') or addr.get('suburb') or '').strip()
    state_full = addr.get('state', '').strip()
    state = STATE_ABBREV.get(state_full, state_full[:2].upper() if state_full else '')
    zip_code = addr.get('postcode', '').strip()
    # Only keep the 5-digit portion of ZIP+4
    if zip_code and '-' in zip_code:
        zip_code = zip_code.split('-')[0]
    return address_line1, city, state, zip_code


def reverse_geocode(lat, lon):
    url = (f"{NOMINATIM_BASE}/reverse?format=json"
           f"&lat={lat}&lon={lon}&zoom=18&addressdetails=1")
    data = nominatim_get(url)
    if data and 'address' in data:
        return parse_address(data['address'])
    return None, None, None, None


def forward_geocode(business_name, city, state):
    q = urllib.parse.quote(f"{business_name} {city} {state} USA")
    url = f"{NOMINATIM_BASE}/search?format=json&q={q}&addressdetails=1&limit=1"
    data = nominatim_get(url)
    if data and len(data) > 0 and 'address' in data[0]:
        return parse_address(data[0]['address'])
    return None, None, None, None


def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    c = db.cursor()

    # Detect coordinate columns
    c.execute('PRAGMA table_info(leads)')
    cols = {r['name'] for r in c.fetchall()}
    lat_col = 'lat' if 'lat' in cols else ('latitude' if 'latitude' in cols else None)
    lon_col = 'lon' if 'lon' in cols else ('longitude' if 'longitude' in cols else None)
    use_reverse = lat_col and lon_col
    geocode_mode = 'reverse (lat/lon)' if use_reverse else 'forward (name + city + state)'
    print(f"Geocoding mode: {geocode_mode}")

    c.execute("""
        SELECT COUNT(*) as n FROM leads
        WHERE status IN ('new','scored') AND address_line1 IS NULL
    """)
    total_needing = c.fetchone()['n']
    print(f"Leads needing address enrichment: {total_needing}")

    if use_reverse:
        c.execute(f"""
            SELECT id, business_name, city, state, {lat_col} AS lat, {lon_col} AS lon
            FROM leads
            WHERE status IN ('new','scored')
              AND address_line1 IS NULL
              AND {lat_col} IS NOT NULL AND {lon_col} IS NOT NULL
            LIMIT {BATCH_LIMIT}
        """)
    else:
        c.execute("""
            SELECT id, business_name, city, state
            FROM leads
            WHERE status IN ('new','scored') AND address_line1 IS NULL
            LIMIT ?
        """, (BATCH_LIMIT,))

    rows = c.fetchall()
    print(f"Processing batch: {len(rows)} leads (limit={BATCH_LIMIT})\n")

    enriched = 0
    failed = 0
    failed_ids = []
    samples = []

    for i, row in enumerate(rows):
        r = dict(row)
        lead_id = r['id']
        name = r.get('business_name') or ''
        city = r.get('city') or ''
        state = r.get('state') or ''

        if use_reverse:
            a1, gcity, gstate, zc = reverse_geocode(r['lat'], r['lon'])
        else:
            a1, gcity, gstate, zc = forward_geocode(name, city, state)

        time.sleep(RATE_LIMIT)

        if a1 and zc:
            c.execute("""
                UPDATE leads
                SET address_line1=?, city=?, state=?, zip_code=?,
                    updated_at=datetime('now')
                WHERE id=?
            """, (a1, gcity or city, gstate or state, zc, lead_id))
            db.commit()
            enriched += 1
            if len(samples) < 3:
                samples.append({
                    'name': name,
                    'address_line1': a1,
                    'city': gcity or city,
                    'state': gstate or state,
                    'zip_code': zc,
                })
        else:
            failed += 1
            failed_ids.append(lead_id)

        if (i + 1) % 25 == 0:
            pct = round((i + 1) / len(rows) * 100)
            print(f"  [{i+1}/{len(rows)}] {pct}%  enriched={enriched}  failed={failed}")

    print(f"\n=== Enrichment Results ===")
    print(f"Leads in batch (had coords/data to work with): {len(rows)}")
    print(f"Successfully enriched:                         {enriched}")
    print(f"Failed (no house# or street found):            {failed}")
    if failed_ids:
        print(f"Failed IDs: {failed_ids[:20]}{'...' if len(failed_ids) > 20 else ''}")

    if samples:
        print(f"\nSample enriched leads:")
        for s in samples:
            print(f"  {s['name']}")
            print(f"    {s['address_line1']}, {s['city']}, {s['state']} {s['zip_code']}")
    else:
        print("\nNo leads were enriched.")

    db.close()


if __name__ == '__main__':
    main()
