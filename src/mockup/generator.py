"""
Mockup generator — builds a free static HTML preview site for a prospect.

Strategy
────────
- GPT-4o-mini generates all copy (cheap, cached by niche)
- Single self-contained index.html with Tailwind CDN + embedded styles
- Niche-specific color palette applied automatically
- Placeholder images via picsum.photos (no external auth needed)
- Output: data/mockups/{lead_id}/index.html

Costs: ~$0.00044 per mockup in API fees.
Caching: system prompt is identical for all leads in the same niche, so
diskcache gets partial benefit on repeated niche calls.
"""

import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Optional

from src.config import CACHE_DIR, AGENCY_NAME, AGENCY_URL, AGENCY_OWNER
from src.ai_client import chat
from src.config import MODEL_DEFAULT

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_MOCKUPS_DIR = _ROOT / "data" / "mockups"
_MOCKUPS_DIR.mkdir(parents=True, exist_ok=True)

# ── Niche color palettes ──────────────────────────────────────────────────────

_NICHE_PALETTES: dict[str, dict] = {
    "restaurant":  {"primary": "#c0392b", "accent": "#e67e22", "bg": "#fdfaf6"},
    "cafe":        {"primary": "#6f4e37", "accent": "#d4a853", "bg": "#faf8f5"},
    "food":        {"primary": "#c0392b", "accent": "#e67e22", "bg": "#fdfaf6"},
    "salon":       {"primary": "#8e44ad", "accent": "#e91e8c", "bg": "#fdf9ff"},
    "barber":      {"primary": "#2c3e50", "accent": "#e74c3c", "bg": "#f8f9fa"},
    "nail":        {"primary": "#e91e63", "accent": "#ff4081", "bg": "#fff5f8"},
    "spa":         {"primary": "#5d4037", "accent": "#a1887f", "bg": "#faf7f5"},
    "photography": {"primary": "#2c3e50", "accent": "#3498db", "bg": "#f8f9fa"},
    "contractor":  {"primary": "#1a5276", "accent": "#f39c12", "bg": "#f8f9fa"},
    "landscaping": {"primary": "#1e8449", "accent": "#f39c12", "bg": "#f5fbf5"},
    "lawn":        {"primary": "#27ae60", "accent": "#f39c12", "bg": "#f5fbf5"},
    "roofing":     {"primary": "#922b21", "accent": "#f39c12", "bg": "#f8f9fa"},
    "plumber":     {"primary": "#1a5276", "accent": "#2ecc71", "bg": "#f5f9ff"},
    "hvac":        {"primary": "#1565c0", "accent": "#ff6f00", "bg": "#f5f9ff"},
    "fitness":     {"primary": "#1e8449", "accent": "#f1c40f", "bg": "#f5fbf5"},
    "gym":         {"primary": "#212121", "accent": "#ff6f00", "bg": "#f5f5f5"},
    "dental":      {"primary": "#0288d1", "accent": "#26c6da", "bg": "#f5fbff"},
    "auto":        {"primary": "#263238", "accent": "#f57c00", "bg": "#f8f9fa"},
    "tire":        {"primary": "#212121", "accent": "#e53935", "bg": "#f8f9fa"},
    "default":     {"primary": "#1a3a5c", "accent": "#2e86c1", "bg": "#f8f9fa"},
}


def _palette(niche: str) -> dict:
    niche_lower = (niche or "").lower()
    for key in _NICHE_PALETTES:
        if key in niche_lower:
            return _NICHE_PALETTES[key]
    return _NICHE_PALETTES["default"]


# ── Copy generation ───────────────────────────────────────────────────────────

_COPY_SYSTEM = """You are a conversion-focused copywriter for local business websites.
Write sharp, specific, benefit-driven copy. Avoid clichés. Sound like a real business,
not a marketing template. Keep everything concise.

Output ONLY valid JSON matching this exact schema:
{
  "tagline": "5-8 word tagline, punchy and specific to this business",
  "hero_subheadline": "1-sentence hero subheadline (max 20 words), benefit-focused",
  "cta_primary": "3-5 word button text (action verb, e.g. 'Book a Free Estimate')",
  "cta_secondary": "2-4 word secondary button text (e.g. 'See Our Work')",
  "services": [
    {"name": "Service name", "description": "1-sentence description, max 15 words"},
    {"name": "Service name", "description": "1-sentence description, max 15 words"},
    {"name": "Service name", "description": "1-sentence description, max 15 words"}
  ],
  "about_blurb": "2-sentence about paragraph, first-person, warm and specific",
  "trust_line": "1 short trust signal (years in business, certifications, or stat)"
}"""


def _generate_copy(lead: dict) -> dict:
    """Call GPT-4o-mini to generate mockup copy. Cached by stable lead fields."""
    business_name = lead.get("business_name", "Your Business")
    niche = lead.get("niche", "local business")
    city = lead.get("city", "")
    state = lead.get("state", "")
    reviews = lead.get("review_count") or 0
    rating = lead.get("google_rating") or 0

    user = (
        f"Business: {business_name}\n"
        f"Type: {niche}\n"
        f"Location: {city}, {state}\n"
        f"Google rating: {rating} stars from {reviews} reviews\n\n"
        f"Write homepage copy for this {niche}. Be specific to their industry and location."
    )

    raw = chat(
        messages=[
            {"role": "system", "content": _COPY_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=MODEL_DEFAULT,
        max_tokens=500,
        temperature=0.4,
        operation="mockup_copy",
        use_cache=True,
    )

    try:
        # Strip markdown fences if present
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        log.warning("JSON parse failed for mockup copy — using fallbacks")
        return {
            "tagline": f"Quality {niche.title()} in {city}",
            "hero_subheadline": f"Serving {city} with pride since day one.",
            "cta_primary": "Contact Us Today",
            "cta_secondary": "Learn More",
            "services": [
                {"name": "Our Services", "description": "Professional service tailored to your needs."},
                {"name": "Quality Work", "description": "Every job done right the first time."},
                {"name": "Local Experts", "description": f"Proud to serve {city} and surrounding areas."},
            ],
            "about_blurb": f"We're {business_name}, a {niche} business in {city}. We take pride in serving our community with quality and care.",
            "trust_line": f"Locally owned and operated in {city}",
        }


# ── HTML template ─────────────────────────────────────────────────────────────

def _build_html(lead: dict, copy: dict) -> str:
    business_name = lead.get("business_name", "Your Business")
    niche = lead.get("niche", "local business")
    city = lead.get("city", "")
    state = lead.get("state", "")
    phone = lead.get("phone", "")
    address = lead.get("address", "")
    pal = _palette(niche)
    primary = pal["primary"]
    accent = pal["accent"]
    bg = pal["bg"]

    svc = copy.get("services", [])
    while len(svc) < 3:
        svc.append({"name": "Our Service", "description": "Professional service you can count on."})

    phone_display = phone if phone else "(555) 555-5555"
    location_display = f"{city}, {state}" if city else "Our Location"
    address_display = address if address else city

    watermark = (
        f'<div style="position:fixed;bottom:12px;right:16px;background:#fff;'
        f'border:1px solid #e2e8f0;border-radius:8px;padding:6px 12px;font-size:11px;'
        f'color:#64748b;z-index:9999;font-family:sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.08);">'
        f'Free mockup by <a href="{AGENCY_URL}" style="color:{primary};text-decoration:none;font-weight:600;">'
        f'{AGENCY_NAME}</a></div>'
    )

    return textwrap.dedent(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{business_name} — {city}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      theme: {{
        extend: {{
          colors: {{
            primary: '{primary}',
            accent: '{accent}',
          }}
        }}
      }}
    }}
  </script>
  <style>
    :root {{ --primary: {primary}; --accent: {accent}; --bg: {bg}; }}
    html {{ scroll-behavior: smooth; }}
    body {{ background-color: {bg}; }}
    .btn-primary {{
      background: {primary};
      color: #fff;
      padding: 14px 28px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 15px;
      display: inline-block;
      text-decoration: none;
      transition: opacity .15s;
    }}
    .btn-primary:hover {{ opacity: .9; }}
    .btn-outline {{
      border: 2px solid {primary};
      color: {primary};
      padding: 12px 26px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 15px;
      display: inline-block;
      text-decoration: none;
      transition: all .15s;
    }}
    .btn-outline:hover {{ background: {primary}; color: #fff; }}
    .hero-bg {{
      background: linear-gradient(135deg, {primary}ee 0%, {primary}99 60%, {accent}66 100%);
      min-height: 520px;
    }}
    .card {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 16px rgba(0,0,0,.07); }}
    .section-accent {{ border-left: 4px solid {accent}; padding-left: 16px; }}
  </style>
</head>
<body class="font-sans antialiased text-gray-800">

  <!-- Nav -->
  <nav class="bg-white shadow-sm sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
      <span class="font-bold text-xl tracking-tight" style="color:{primary}">{business_name}</span>
      <div class="hidden md:flex gap-6 text-sm font-medium text-gray-600">
        <a href="#services" class="hover:text-gray-900 transition">Services</a>
        <a href="#about" class="hover:text-gray-900 transition">About</a>
        <a href="#contact" class="hover:text-gray-900 transition">Contact</a>
      </div>
      <a href="tel:{phone}" class="btn-primary text-sm py-2 px-5">
        {'📞 ' + phone_display if phone else 'Call Us'}
      </a>
    </div>
  </nav>

  <!-- Hero -->
  <section class="hero-bg flex items-center">
    <div class="max-w-6xl mx-auto px-4 py-20 md:py-28">
      <div class="max-w-2xl">
        <p class="text-white/80 text-sm font-semibold uppercase tracking-widest mb-3">
          {location_display}
        </p>
        <h1 class="text-white text-4xl md:text-5xl font-extrabold leading-tight mb-4">
          {copy.get("tagline", business_name)}
        </h1>
        <p class="text-white/90 text-lg md:text-xl mb-8 leading-relaxed">
          {copy.get("hero_subheadline", "")}
        </p>
        <div class="flex flex-wrap gap-4">
          <a href="#contact" class="btn-primary">{copy.get("cta_primary", "Contact Us")}</a>
          <a href="#services" class="btn-outline" style="border-color:#fff;color:#fff"
             onmouseover="this.style.background='#fff';this.style.color='{primary}'"
             onmouseout="this.style.background='transparent';this.style.color='#fff'">
            {copy.get("cta_secondary", "Learn More")}
          </a>
        </div>
      </div>
    </div>
  </section>

  <!-- Trust bar -->
  <div class="bg-white border-b border-gray-100 py-4">
    <div class="max-w-6xl mx-auto px-4 text-center text-sm text-gray-500 font-medium">
      {copy.get("trust_line", f"Serving {city} with quality and care")}
    </div>
  </div>

  <!-- Services -->
  <section id="services" class="py-20">
    <div class="max-w-6xl mx-auto px-4">
      <h2 class="text-3xl font-bold text-gray-900 mb-2">What We Do</h2>
      <p class="text-gray-500 mb-10">Professional services you can count on.</p>
      <div class="grid md:grid-cols-3 gap-6">
        {_service_cards(svc, primary, accent)}
      </div>
    </div>
  </section>

  <!-- About -->
  <section id="about" class="py-20" style="background:#fff">
    <div class="max-w-6xl mx-auto px-4">
      <div class="grid md:grid-cols-2 gap-12 items-center">
        <div>
          <h2 class="text-3xl font-bold text-gray-900 mb-4">About Us</h2>
          <div class="section-accent mb-6">
            <p class="text-gray-600 text-lg leading-relaxed">
              {copy.get("about_blurb", f"We are {business_name}, a trusted {niche} in {city}.")}
            </p>
          </div>
          <a href="#contact" class="btn-primary">{copy.get("cta_primary", "Get in Touch")}</a>
        </div>
        <div class="rounded-xl overflow-hidden shadow-lg bg-gray-100 h-64 md:h-80 flex items-center justify-center"
             style="background: linear-gradient(135deg, {primary}22, {accent}22)">
          <span class="text-gray-400 text-sm">[Your photo here]</span>
        </div>
      </div>
    </div>
  </section>

  <!-- Contact -->
  <section id="contact" class="py-20" style="background:{bg}">
    <div class="max-w-6xl mx-auto px-4">
      <h2 class="text-3xl font-bold text-gray-900 mb-2">Get in Touch</h2>
      <p class="text-gray-500 mb-10">We'd love to hear from you.</p>
      <div class="grid md:grid-cols-2 gap-10">
        <div class="card p-8">
          <form class="space-y-4" onsubmit="return false">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Your Name</label>
              <input type="text" placeholder="Jane Smith"
                     class="w-full border border-gray-200 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2"
                     style="--tw-ring-color:{primary}40" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input type="email" placeholder="jane@example.com"
                     class="w-full border border-gray-200 rounded-lg px-4 py-3 text-sm focus:outline-none" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Message</label>
              <textarea rows="4" placeholder="How can we help?"
                        class="w-full border border-gray-200 rounded-lg px-4 py-3 text-sm focus:outline-none resize-none"></textarea>
            </div>
            <button type="submit" class="btn-primary w-full text-center"
                    style="background:{primary}">Send Message</button>
          </form>
        </div>
        <div class="space-y-6">
          <div class="card p-6">
            <h3 class="font-semibold text-gray-900 mb-3">Contact Info</h3>
            <div class="space-y-2 text-sm text-gray-600">
              {'<p>📞 <a href="tel:' + phone + '" class="font-medium">' + phone_display + '</a></p>' if phone else ''}
              {'<p>📍 ' + address_display + '</p>' if address_display else ''}
            </div>
          </div>
          <div class="card p-6">
            <h3 class="font-semibold text-gray-900 mb-3">Business Hours</h3>
            <div class="text-sm text-gray-600 space-y-1">
              <p>Monday – Friday: <span class="font-medium">9:00 AM – 5:00 PM</span></p>
              <p>Saturday: <span class="font-medium">10:00 AM – 3:00 PM</span></p>
              <p>Sunday: <span class="font-medium">Closed</span></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Footer -->
  <footer class="py-8 text-center text-sm text-gray-400 border-t border-gray-100 bg-white">
    <p class="font-semibold text-gray-700 mb-1">{business_name}</p>
    <p>{address_display}</p>
    {f'<p class="mt-1"><a href="tel:{phone}" class="hover:text-gray-600">{phone_display}</a></p>' if phone else ''}
    <p class="mt-4 text-xs text-gray-300">© {business_name} · {city}</p>
  </footer>

  {watermark}

</body>
</html>""")


def _service_cards(services: list, primary: str, accent: str) -> str:
    icons = ["⚡", "✅", "🏆"]
    cards = []
    for i, svc in enumerate(services[:3]):
        icon = icons[i % len(icons)]
        cards.append(f"""
        <div class="card p-8">
          <div class="text-3xl mb-4">{icon}</div>
          <h3 class="font-bold text-lg text-gray-900 mb-2">{svc.get("name", "Service")}</h3>
          <p class="text-gray-500 text-sm leading-relaxed">{svc.get("description", "")}</p>
        </div>""")
    return "\n".join(cards)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_mockup(lead: dict) -> Path:
    """
    Generate a free mockup HTML site for the given lead.

    Returns the path to the generated index.html.
    """
    lead_id = lead.get("id")
    if not lead_id:
        raise ValueError("lead must have an 'id' field")

    out_dir = _MOCKUPS_DIR / str(lead_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"

    log.info("Generating mockup for lead #%d: %s", lead_id, lead.get("business_name"))

    copy = _generate_copy(lead)
    html = _build_html(lead, copy)

    out_path.write_text(html, encoding="utf-8")
    log.info("Mockup written to %s", out_path)
    return out_path
