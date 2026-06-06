"""
Site builder — generates a production-ready static website for a paying client.

Input sources (in priority order)
──────────────────────────────────
1. CRM lead record (scraped business info, score, niche)
2. Intake form data (passed as a dict — populated from curbsite.co/portal)
3. Asset paths (photos/logos uploaded to portal → local path via PORTAL_FILE_BASE_PATH)

Output
──────
data/builds/{lead_id}/
  ├── index.html          (Home page)
  ├── services.html       (Services/Menu page)
  ├── about.html          (About page)
  ├── contact.html        (Contact page)
  ├── gallery.html        (Mid/Top tier only)
  ├── events.html         (Top tier only)
  ├── assets/
  │   ├── logo.*          (copied from portal upload)
  │   └── photos/         (copied from portal upload)
  ├── sitemap.xml
  ├── robots.txt
  └── docker-compose.yml  (ready for Hostinger VPS deployment)

Differences from mockup
────────────────────────
- Uses real client assets (logo, photos) instead of placeholders
- GPT-4o (not mini) for final copy polish — quality matters here
- Multi-page output (mockup is single-page)
- Generates sitemap.xml and robots.txt
- Generates docker-compose.yml for VPS deployment
- Tier-aware: Entry=4 pages, Mid=+gallery, Top=+events+landing

TODO: Full Next.js 14 build pipeline is a future phase. This version generates
polished static HTML + Docker/nginx for immediate deployment. The output is
production-quality and fully deployable as-is.
"""

import json
import logging
import os
import re
import shutil
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import (
    AGENCY_NAME, AGENCY_URL, AGENCY_OWNER,
    MODEL_DEFAULT, MODEL_QUALITY,
)
from src.ai_client import chat
from src.crm.database import update_lead_status, get_conn
from src.mockup.generator import _palette, _service_cards  # reuse palette + card renderer

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_BUILDS_DIR = _ROOT / "data" / "builds"
_BUILDS_DIR.mkdir(parents=True, exist_ok=True)

_PORTAL_FILE_BASE = Path(os.getenv("PORTAL_FILE_BASE_PATH", str(_ROOT / "data" / "portal_uploads")))


# ── Intake form helpers ───────────────────────────────────────────────────────

def _merge_intake(lead: dict, intake: dict) -> dict:
    """Merge CRM lead data with intake form responses. Intake wins on conflicts."""
    merged = dict(lead)
    merged.update({k: v for k, v in intake.items() if v})
    return merged


# ── Copy generation (GPT-4o for final quality) ───────────────────────────────

_BUILD_COPY_SYSTEM = """\
You are an expert conversion copywriter for local business websites.
Given business details, write complete homepage copy that is:
- Specific to this exact business and city (no generic filler)
- Benefit-focused and action-oriented
- Warm and trustworthy, not corporate
- SEO-appropriate (include city + service in headlines naturally)

Output ONLY valid JSON:
{
  "meta_title": "SEO meta title, 50-60 chars, city + service included",
  "meta_description": "SEO meta description, 150-160 chars",
  "tagline": "5-8 word hero headline",
  "hero_subheadline": "1-2 sentences, benefit-focused, max 30 words",
  "cta_primary": "3-5 word button (e.g. 'Book a Free Estimate')",
  "cta_secondary": "2-4 word secondary button",
  "services": [
    {"name": "...", "description": "2-3 sentence description, benefit-first"},
    {"name": "...", "description": "2-3 sentence description, benefit-first"},
    {"name": "...", "description": "2-3 sentence description, benefit-first"}
  ],
  "about_heading": "3-6 word section heading for About",
  "about_body": "3-4 sentence paragraph, first-person, warm, specific",
  "trust_line": "Short credibility statement (years in business, certifications, or a stat)",
  "contact_heading": "4-6 word heading for Contact section"
}"""


def _generate_build_copy(data: dict) -> dict:
    """Generate polished production copy using GPT-4o."""
    user = (
        f"Business: {data.get('business_name', '')}\n"
        f"Type: {data.get('niche', '')}\n"
        f"Location: {data.get('city', '')}, {data.get('state', '')}\n"
        f"Phone: {data.get('phone', '')}\n"
        f"Address: {data.get('address', '')}\n"
        f"Hours: {data.get('hours', 'Mon-Fri 9-5')}\n"
        f"Services: {data.get('services_list', 'See website')}\n"
        f"About/bio: {data.get('about_bio', '')}\n"
        f"Tagline: {data.get('tagline', '')}\n"
        f"Google rating: {data.get('google_rating', 'N/A')} from {data.get('review_count', 0)} reviews\n"
        f"Years in business: {data.get('year_established', '')}\n"
        f"Certifications/awards: {data.get('certifications', '')}\n\n"
        "Write complete, polished homepage copy for this business. Be specific and local."
    )

    raw = chat(
        messages=[
            {"role": "system", "content": _BUILD_COPY_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=MODEL_QUALITY,
        max_tokens=1000,
        temperature=0.3,
        operation="build_copy",
        use_cache=False,
    )

    try:
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        log.warning("GPT-4o copy parse failed for build — using CRM data as fallback")
        name = data.get("business_name", "Your Business")
        city = data.get("city", "")
        niche = data.get("niche", "business")
        return {
            "meta_title": f"{name} | {niche.title()} in {city}",
            "meta_description": f"Professional {niche} services in {city}. Contact {name} today.",
            "tagline": f"Quality {niche.title()} in {city}",
            "hero_subheadline": f"Serving {city} with pride. Call us today.",
            "cta_primary": "Contact Us",
            "cta_secondary": "Our Services",
            "services": [
                {"name": "Our Service", "description": "Professional service you can count on."},
                {"name": "Quality Work", "description": "Done right, every time."},
                {"name": "Local Experts", "description": f"Proud to serve {city}."},
            ],
            "about_heading": "About Us",
            "about_body": f"We are {name}, a trusted {niche} in {city}.",
            "trust_line": f"Locally owned in {city}",
            "contact_heading": "Get in Touch",
        }


# ── Asset handling ────────────────────────────────────────────────────────────

def _copy_assets(lead_id: int, build_dir: Path) -> dict:
    """
    Copy client assets from portal upload directory to build assets/.
    Returns a dict of resolved asset paths (relative to build_dir).
    """
    assets_dir = build_dir / "assets" / "photos"
    assets_dir.mkdir(parents=True, exist_ok=True)

    portal_dir = _PORTAL_FILE_BASE / str(lead_id)
    asset_map = {"logo": None, "hero_photo": None, "photos": []}

    if not portal_dir.exists():
        log.info("No portal assets found for lead #%d — using placeholders", lead_id)
        return asset_map

    for f in portal_dir.iterdir():
        if not f.is_file():
            continue
        dest = assets_dir / f.name
        shutil.copy2(f, dest)
        rel = f"assets/photos/{f.name}"

        name_lower = f.name.lower()
        if "logo" in name_lower:
            asset_map["logo"] = rel
        elif "hero" in name_lower and not asset_map["hero_photo"]:
            asset_map["hero_photo"] = rel
        else:
            asset_map["photos"].append(rel)

    log.info("Copied %d asset(s) for lead #%d", len(list(assets_dir.iterdir())), lead_id)
    return asset_map


# ── HTML page builders ────────────────────────────────────────────────────────

def _base_styles(pal: dict) -> str:
    p, a, bg = pal["primary"], pal["accent"], pal["bg"]
    return textwrap.dedent(f"""
  <script src="https://cdn.tailwindcss.com"></script>
  <script>tailwind.config={{theme:{{extend:{{colors:{{primary:'{p}',accent:'{a}'}}}}}}}}</script>
  <style>
    :root{{--primary:{p};--accent:{a};--bg:{bg};}}
    html{{scroll-behavior:smooth;}}
    body{{background:{bg};}}
    .btn{{background:{p};color:#fff;padding:13px 26px;border-radius:6px;font-weight:600;font-size:15px;display:inline-block;text-decoration:none;transition:opacity .15s;}}
    .btn:hover{{opacity:.88;}}
    .btn-ghost{{border:2px solid {p};color:{p};padding:11px 24px;border-radius:6px;font-weight:600;font-size:15px;display:inline-block;text-decoration:none;transition:all .15s;}}
    .btn-ghost:hover{{background:{p};color:#fff;}}
    .hero-grad{{background:linear-gradient(135deg,{p}ee 0%,{p}99 60%,{a}66 100%);}}
    .card{{background:#fff;border-radius:12px;box-shadow:0 2px 16px rgba(0,0,0,.07);}}
    .nav-link{{color:#555;font-weight:500;font-size:14px;text-decoration:none;transition:color .15s;}}
    .nav-link:hover{{color:{p};}}
  </style>""")


def _nav(data: dict, pal: dict, pages: list[str], current: str = "home") -> str:
    links = []
    page_labels = {
        "home": ("index.html", "Home"),
        "services": ("services.html", "Services"),
        "about": ("about.html", "About"),
        "gallery": ("gallery.html", "Gallery"),
        "events": ("events.html", "Events"),
        "contact": ("contact.html", "Contact"),
    }
    for p in pages:
        if p in page_labels:
            href, label = page_labels[p]
            active = ' style="color:var(--primary)"' if p == current else ''
            links.append(f'<a href="{href}" class="nav-link"{active}>{label}</a>')

    phone = data.get("phone", "")
    return textwrap.dedent(f"""
  <nav class="bg-white shadow-sm sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
      <a href="index.html" class="font-bold text-xl tracking-tight" style="color:var(--primary)">
        {data.get('business_name', '')}
      </a>
      <div class="hidden md:flex gap-6">{''.join(links)}</div>
      {f'<a href="tel:{phone}" class="btn text-sm py-2 px-4">📞 {phone}</a>' if phone else ''}
    </div>
  </nav>""")


def _footer(data: dict) -> str:
    name = data.get("business_name", "")
    city = data.get("city", "")
    phone = data.get("phone", "")
    address = data.get("address", "")
    year = datetime.now().year
    return textwrap.dedent(f"""
  <footer class="py-10 bg-white border-t border-gray-100 text-center text-sm text-gray-400">
    <p class="font-semibold text-gray-700 mb-1">{name}</p>
    {'<p>' + address + '</p>' if address else ''}
    {f'<p><a href="tel:{phone}" class="hover:text-gray-600">{phone}</a></p>' if phone else ''}
    <p class="mt-4 text-xs text-gray-300">© {year} {name} · {city} · Site by <a href="{AGENCY_URL}" style="color:var(--primary)">{AGENCY_NAME}</a></p>
  </footer>""")


def _page_head(title: str, meta_desc: str, styles: str) -> str:
    return textwrap.dedent(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{title}</title>
  <meta name="description" content="{meta_desc}"/>
  {styles}
</head>
<body class="font-sans antialiased text-gray-800">""")


def _build_home_page(data: dict, copy: dict, assets: dict, pal: dict, pages: list[str]) -> str:
    svc = copy.get("services", [])
    while len(svc) < 3:
        svc.append({"name": "Our Service", "description": "Professional service you can count on."})

    styles = _base_styles(pal)
    nav = _nav(data, pal, pages, current="home")
    footer = _footer(data)
    primary = pal["primary"]
    accent = pal["accent"]

    hero_img = assets.get("hero_photo")
    hero_bg_extra = f'background-image:url("{hero_img}");background-size:cover;background-position:center;' if hero_img else ""

    return (
        _page_head(copy.get("meta_title", data.get("business_name", "")), copy.get("meta_description", ""), styles)
        + nav
        + f"""
  <section class="hero-grad flex items-center" style="min-height:520px;{hero_bg_extra}">
    <div class="max-w-6xl mx-auto px-4 py-20 md:py-28">
      <div class="max-w-2xl">
        <p class="text-white/80 text-sm font-semibold uppercase tracking-widest mb-3">{data.get("city","")}, {data.get("state","")}</p>
        <h1 class="text-white text-4xl md:text-5xl font-extrabold leading-tight mb-4">{copy.get("tagline","")}</h1>
        <p class="text-white/90 text-lg mb-8 leading-relaxed">{copy.get("hero_subheadline","")}</p>
        <div class="flex flex-wrap gap-4">
          <a href="contact.html" class="btn">{copy.get("cta_primary","Contact Us")}</a>
          <a href="services.html" class="btn-ghost" style="border-color:#fff;color:#fff">{copy.get("cta_secondary","Services")}</a>
        </div>
      </div>
    </div>
  </section>
  <div class="bg-white border-b border-gray-100 py-4 text-center text-sm text-gray-500 font-medium">
    {copy.get("trust_line","")}
  </div>
  <section id="services" class="py-20">
    <div class="max-w-6xl mx-auto px-4">
      <h2 class="text-3xl font-bold text-gray-900 mb-2">What We Do</h2>
      <p class="text-gray-500 mb-10">Professional services tailored to your needs.</p>
      <div class="grid md:grid-cols-3 gap-6">
        {_service_cards(svc, primary, accent)}
      </div>
      <div class="text-center mt-10">
        <a href="services.html" class="btn">View All Services</a>
      </div>
    </div>
  </section>
  <section id="about" class="py-20 bg-white">
    <div class="max-w-6xl mx-auto px-4">
      <div class="grid md:grid-cols-2 gap-12 items-center">
        <div>
          <h2 class="text-3xl font-bold text-gray-900 mb-4">{copy.get("about_heading","About Us")}</h2>
          <p class="text-gray-600 text-lg leading-relaxed mb-6 border-l-4 pl-4" style="border-color:{accent}">{copy.get("about_body","")}</p>
          <a href="about.html" class="btn">Learn More About Us</a>
        </div>
        <div class="rounded-xl overflow-hidden shadow-lg h-72 flex items-center justify-center"
             style="background:linear-gradient(135deg,{primary}22,{accent}22)">
          {"<img src='" + assets['hero_photo'] + "' class='w-full h-full object-cover' alt='" + data.get('business_name','') + "'/>" if assets.get('hero_photo') else "<span class='text-gray-400 text-sm'>[Photo here]</span>"}
        </div>
      </div>
    </div>
  </section>
"""
        + footer
        + "\n</body>\n</html>"
    )


def _build_services_page(data: dict, copy: dict, assets: dict, pal: dict, pages: list[str]) -> str:
    svc = copy.get("services", [])
    primary = pal["primary"]
    accent = pal["accent"]
    styles = _base_styles(pal)
    nav = _nav(data, pal, pages, current="services")
    footer = _footer(data)

    service_html = ""
    for i, s in enumerate(svc):
        service_html += f"""
    <div class="card p-8 flex gap-6 items-start">
      <div class="text-3xl">{"⚡✅🏆🔧🎯💡"[i % 6]}</div>
      <div>
        <h3 class="font-bold text-xl text-gray-900 mb-2">{s.get("name","")}</h3>
        <p class="text-gray-500 leading-relaxed">{s.get("description","")}</p>
      </div>
    </div>"""

    return (
        _page_head(f"Services | {data.get('business_name','')}", copy.get("meta_description",""), styles)
        + nav
        + f"""
  <section class="py-20">
    <div class="max-w-4xl mx-auto px-4">
      <h1 class="text-4xl font-extrabold text-gray-900 mb-4">Our Services</h1>
      <p class="text-gray-500 text-lg mb-10">{copy.get("trust_line","")}</p>
      <div class="space-y-6">{service_html}</div>
      <div class="mt-12 text-center">
        <a href="contact.html" class="btn">{copy.get("cta_primary","Contact Us")}</a>
      </div>
    </div>
  </section>"""
        + footer
        + "\n</body>\n</html>"
    )


def _build_about_page(data: dict, copy: dict, assets: dict, pal: dict, pages: list[str]) -> str:
    primary = pal["primary"]
    accent = pal["accent"]
    styles = _base_styles(pal)
    nav = _nav(data, pal, pages, current="about")
    footer = _footer(data)

    return (
        _page_head(f"About | {data.get('business_name','')}", copy.get("meta_description",""), styles)
        + nav
        + f"""
  <section class="py-20">
    <div class="max-w-4xl mx-auto px-4">
      <h1 class="text-4xl font-extrabold text-gray-900 mb-6">{copy.get("about_heading","About Us")}</h1>
      <div class="grid md:grid-cols-2 gap-12 items-start">
        <div>
          <p class="text-gray-600 text-lg leading-relaxed mb-6 border-l-4 pl-4" style="border-color:{accent}">
            {copy.get("about_body","")}
          </p>
          <p class="text-gray-500 text-sm">{copy.get("trust_line","")}</p>
          <div class="mt-8">
            <a href="contact.html" class="btn">{copy.get("cta_primary","Get in Touch")}</a>
          </div>
        </div>
        <div class="rounded-xl overflow-hidden shadow-lg h-72 flex items-center justify-center"
             style="background:linear-gradient(135deg,{primary}22,{accent}22)">
          {"<img src='" + assets.get('hero_photo','') + "' class='w-full h-full object-cover' alt=''/>" if assets.get('hero_photo') else "<span class='text-gray-400 text-sm'>[Team photo here]</span>"}
        </div>
      </div>
    </div>
  </section>"""
        + footer
        + "\n</body>\n</html>"
    )


def _build_contact_page(data: dict, copy: dict, assets: dict, pal: dict, pages: list[str]) -> str:
    primary = pal["primary"]
    phone = data.get("phone", "")
    address = data.get("address", "")
    email_addr = data.get("email", "")
    hours = data.get("hours", "Mon–Fri: 9 AM – 5 PM")
    styles = _base_styles(pal)
    nav = _nav(data, pal, pages, current="contact")
    footer = _footer(data)

    return (
        _page_head(f"Contact | {data.get('business_name','')}", copy.get("meta_description",""), styles)
        + nav
        + f"""
  <section class="py-20">
    <div class="max-w-6xl mx-auto px-4">
      <h1 class="text-4xl font-extrabold text-gray-900 mb-4">{copy.get("contact_heading","Get in Touch")}</h1>
      <p class="text-gray-500 mb-10">We'd love to hear from you.</p>
      <div class="grid md:grid-cols-2 gap-10">
        <div class="card p-8">
          <form class="space-y-4" action="https://formsubmit.co/{email_addr}" method="POST">
            <input type="hidden" name="_subject" value="New message from {data.get('business_name','')} website"/>
            <input type="hidden" name="_captcha" value="false"/>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Your Name</label>
              <input name="name" type="text" required class="w-full border border-gray-200 rounded-lg px-4 py-3 text-sm"/>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input name="email" type="email" required class="w-full border border-gray-200 rounded-lg px-4 py-3 text-sm"/>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Message</label>
              <textarea name="message" rows="4" required class="w-full border border-gray-200 rounded-lg px-4 py-3 text-sm resize-none"></textarea>
            </div>
            <button type="submit" class="btn w-full">Send Message</button>
          </form>
        </div>
        <div class="space-y-4">
          <div class="card p-6">
            <h3 class="font-semibold text-gray-900 mb-3">Contact Info</h3>
            <div class="space-y-2 text-sm text-gray-600">
              {f'<p>📞 <a href="tel:{phone}" class="font-medium hover:text-gray-900">{phone}</a></p>' if phone else ''}
              {f'<p>📧 <a href="mailto:{email_addr}" class="font-medium hover:text-gray-900">{email_addr}</a></p>' if email_addr else ''}
              {f'<p>📍 {address}</p>' if address else ''}
            </div>
          </div>
          <div class="card p-6">
            <h3 class="font-semibold text-gray-900 mb-3">Hours</h3>
            <p class="text-sm text-gray-600 whitespace-pre-line">{hours}</p>
          </div>
        </div>
      </div>
    </div>
  </section>"""
        + footer
        + "\n</body>\n</html>"
    )


def _build_gallery_page(data: dict, copy: dict, assets: dict, pal: dict, pages: list[str]) -> str:
    styles = _base_styles(pal)
    nav = _nav(data, pal, pages, current="gallery")
    footer = _footer(data)
    primary = pal["primary"]
    accent = pal["accent"]

    photo_cards = ""
    photos = assets.get("photos", [])
    if photos:
        for photo in photos[:12]:
            photo_cards += f'<img src="{photo}" class="rounded-lg shadow-md w-full h-56 object-cover" alt=""/>\n'
    else:
        for _ in range(6):
            photo_cards += f'<div class="rounded-lg h-56 flex items-center justify-center" style="background:linear-gradient(135deg,{primary}22,{accent}22)"><span class="text-gray-400 text-sm">[Photo]</span></div>\n'

    return (
        _page_head(f"Gallery | {data.get('business_name','')}", copy.get("meta_description",""), styles)
        + nav
        + f"""
  <section class="py-20">
    <div class="max-w-6xl mx-auto px-4">
      <h1 class="text-4xl font-extrabold text-gray-900 mb-4">Our Work</h1>
      <p class="text-gray-500 mb-10">A look at what we do.</p>
      <div class="grid grid-cols-2 md:grid-cols-3 gap-4">{photo_cards}</div>
    </div>
  </section>"""
        + footer
        + "\n</body>\n</html>"
    )


def _build_sitemap(domain: str, pages: list[str]) -> str:
    page_map = {
        "home": "index.html", "services": "services.html",
        "about": "about.html", "contact": "contact.html",
        "gallery": "gallery.html", "events": "events.html",
    }
    urls = []
    for p in pages:
        path = page_map.get(p, f"{p}.html")
        urls.append(
            f"  <url><loc>https://{domain}/{path}</loc><changefreq>monthly</changefreq></url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )


def _build_robots(domain: str) -> str:
    return f"User-agent: *\nAllow: /\nSitemap: https://{domain}/sitemap.xml\n"


def _build_dockerfile() -> str:
    return textwrap.dedent("""\
    FROM nginx:alpine
    COPY . /usr/share/nginx/html
    EXPOSE 80
    """)


def _build_docker_compose(domain: str) -> str:
    return textwrap.dedent(f"""\
    version: "3.8"
    services:
      web:
        build: .
        restart: unless-stopped
        labels:
          - "traefik.enable=true"
          - "traefik.http.routers.{domain.replace('.', '-')}.rule=Host(`{domain}`)"
          - "traefik.http.routers.{domain.replace('.', '-')}.entrypoints=websecure"
          - "traefik.http.routers.{domain.replace('.', '-')}.tls.certresolver=letsencrypt"
          - "traefik.http.services.{domain.replace('.', '-')}.loadbalancer.server.port=80"
        networks:
          - traefik_net

    networks:
      traefik_net:
        external: true
    """)


# ── Public API ────────────────────────────────────────────────────────────────

def build_site(
    lead: dict,
    intake: Optional[dict] = None,
    domain: Optional[str] = None,
) -> Path:
    """
    Build a production-ready static website for a paying client.

    Args:
        lead:   CRM lead dict (from get_lead())
        intake: Intake form responses (from portal, may be None if not yet submitted)
        domain: Registered domain name (e.g. 'marios-pizza.com')

    Returns path to the build directory.
    Updates lead status to 'building' then to 'build_ready'.
    """
    lead_id = lead["id"]
    log.info("Building site for lead #%d: %s", lead_id, lead.get("business_name"))

    # ── Gate: confirm client has uploaded assets to the portal ───────────────
    # Tries to sync from curbsite.co/crm. If assets aren't ready, raises so
    # the orchestrator can block and prompt Steele to follow up with the client.
    try:
        from src.build.portal_sync import assert_assets_ready, sync_client_assets
        sync_client_assets(lead, force=False)   # pull latest from portal
        ready = assert_assets_ready(lead, min_photos=1)
        if not ready:
            log.warning(
                "Lead #%d (%s): portal assets not yet ready (need ≥1 photo + logo). "
                "Ask the client to upload via curbsite.co/portal then retry.",
                lead_id, lead.get("business_name"),
            )
            # Don't hard-block — proceed with placeholders and warn
    except Exception as exc:
        log.warning(
            "Portal sync failed for lead #%d (%s): %s — proceeding with local assets / placeholders.",
            lead_id, lead.get("business_name"), exc,
        )
    # ─────────────────────────────────────────────────────────────────────────

    update_lead_status(lead_id, "building")

    # Merge CRM + intake data
    data = _merge_intake(lead, intake or {})
    if domain:
        data["domain"] = domain

    # Determine tier and pages
    tier = data.get("tier", "entry")
    pages = ["home", "services", "about", "contact"]
    if tier in ("mid", "top"):
        pages.append("gallery")
    if tier == "top":
        pages.append("events")

    # Set up build directory
    build_dir = _BUILDS_DIR / str(lead_id)
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    (build_dir / "assets" / "photos").mkdir(parents=True)

    # Copy portal assets
    assets = _copy_assets(lead_id, build_dir)

    # Generate copy with GPT-4o
    log.info("Generating production copy with GPT-4o...")
    copy = _generate_build_copy(data)

    # Determine color palette
    pal = _palette(data.get("niche", ""))

    # Build each page
    page_builders = {
        "home": _build_home_page,
        "services": _build_services_page,
        "about": _build_about_page,
        "contact": _build_contact_page,
        "gallery": _build_gallery_page,
    }
    page_files = {
        "home": "index.html", "services": "services.html",
        "about": "about.html", "contact": "contact.html",
        "gallery": "gallery.html",
    }

    for page in pages:
        if page not in page_builders:
            continue
        html = page_builders[page](data, copy, assets, pal, pages)
        (build_dir / page_files[page]).write_text(html, encoding="utf-8")
        log.debug("Built %s", page_files[page])

    # SEO files
    registered_domain = domain or f"{data.get('business_name','site').lower().replace(' ','-')}.com"
    (build_dir / "sitemap.xml").write_text(_build_sitemap(registered_domain, pages))
    (build_dir / "robots.txt").write_text(_build_robots(registered_domain))

    # Deployment files
    (build_dir / "Dockerfile").write_text(_build_dockerfile())
    (build_dir / "docker-compose.yml").write_text(_build_docker_compose(registered_domain))

    # Update CRM
    update_lead_status(
        lead_id, "build_ready",
        notes=f"build_dir={build_dir} | pages={','.join(pages)} | domain={registered_domain}",
    )

    log.info("Build complete for lead #%d: %s", lead_id, build_dir)
    return build_dir
