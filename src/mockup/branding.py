import os, requests
from io import BytesIO

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

def _get_place_photos(business_name, city, state):
    if not GOOGLE_API_KEY:
        return []
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={"query": f"{business_name} {city} {state}", "key": GOOGLE_API_KEY}, timeout=8)
        results = r.json().get("results", [])
        if not results:
            return []
        return [f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photoreference={p['photo_reference']}&key={GOOGLE_API_KEY}"
                for p in results[0].get("photos", [])[:3]]
    except Exception:
        return []

def _extract_colors_from_url(url):
    try:
        from colorthief import ColorThief
        r = requests.get(url, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return None
        ct = ColorThief(BytesIO(r.content))
        d = ct.get_color(quality=1)
        p = ct.get_palette(color_count=5, quality=1)
        a = max(p, key=lambda c: sum(abs(c[i]-d[i]) for i in range(3)))
        h = lambda rgb: "#{:02x}{:02x}{:02x}".format(*rgb)
        return {"primary": h(d), "accent": h(a), "palette": [h(c) for c in p]}
    except Exception:
        return None

def get_brand_assets(lead):
    photos = _get_place_photos(lead.get("business_name",""), lead.get("city",""), lead.get("state",""))
    for url in photos:
        colors = _extract_colors_from_url(url)
        if colors:
            return {**colors, "image_url": url}
    return {"image_url": photos[0]} if photos else {}
