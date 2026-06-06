"""
Track B deployment — zip the built site and email it to the client.

Use this when:
  - Client did NOT purchase a Curbsite maintenance plan
  - Client has their own hosting (GoDaddy, Bluehost, etc.)
  - Client explicitly requested source files

The zip includes:
  - Full Next.js build output (/out) — static export ready for any host
  - docker-compose.yml + Dockerfile — for VPS self-hosting
  - A README with plain-English instructions for three scenarios:
      A. Upload to existing cPanel/FTP host
      B. Deploy on a VPS (Docker Compose)
      C. Drop into Netlify/Vercel

The email is sent to the lead's email and CC's steele.stout@gmail.com.

Payment reminder is NOT included here — by the time this runs, the
client has already paid their final 50%. This is a clean delivery email.
"""

import logging
import os
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

from src.config import AGENCY_NAME, AGENCY_OWNER, AGENCY_URL
from src.crm.database import update_lead_status
from src.notifications.transactional import send_transactional

log = logging.getLogger(__name__)

_SUPPORT_EMAIL = "steele.stout@gmail.com"
_CARE_PLAN_UPGRADE_URL = f"{AGENCY_URL}/care"


# ── README template ───────────────────────────────────────────────────────────

def _build_readme(lead: dict, domain: str) -> str:
    business = lead.get("business_name", "Your Business")
    today = date.today().strftime("%B %d, %Y")
    return f"""# {business} — Website Delivery

Delivered by {AGENCY_NAME} on {today}

---

## What's in this package

- `/out/` — Static HTML/CSS/JS export of your website (upload this folder to go live)
- `Dockerfile` + `docker-compose.yml` — For self-hosting on a VPS with Docker
- `sitemap.xml`, `robots.txt` — Pre-configured SEO files

---

## How to go live

### Option A — Upload to existing host (GoDaddy, Bluehost, cPanel, etc.)

1. Log in to your hosting control panel
2. Go to File Manager → public_html (or www)
3. Upload everything inside the `/out/` folder
4. Point your domain to that folder (it may already be)
5. Done — your site should be live within minutes

### Option B — VPS hosting with Docker

1. SSH into your server
2. Copy this entire folder to your server (e.g. `/var/www/{domain}`)
3. `cd /var/www/{domain} && docker compose up -d`
4. Update your DNS A record to point to your server's IP
5. Done

### Option C — Netlify / Vercel (free tier)

1. Create a free account at netlify.com or vercel.com
2. Drag the `/out/` folder onto the Netlify dashboard
3. Claim a custom domain in their settings and update your DNS

---

## Updating your site later

If you want to make changes yourself:
- The HTML files are in `/out/` — you can edit them with any text editor
- Images are in `/out/images/`

Or contact {AGENCY_NAME} for updates. {AGENCY_OWNER} can handle any edits, or
you can sign up for a monthly care plan at:
  {_CARE_PLAN_UPGRADE_URL}

---

## Questions?

Email: {_SUPPORT_EMAIL}
Phone/text: available via curbsite.co

---

Domain: {domain if domain else "(set up your domain separately)"}
Delivered: {today}
"""


# ── Zip builder ───────────────────────────────────────────────────────────────

def create_handoff_zip(lead: dict, build_dir: Path, domain: str) -> Path:
    """
    Zip the built site directory + a README into a single deliverable.
    Returns the path to the created zip file.
    """
    lead_id = lead["id"]
    business_slug = (lead.get("business_name") or f"site-{lead_id}").lower()
    business_slug = "".join(c if c.isalnum() or c == "-" else "-" for c in business_slug)
    business_slug = business_slug.strip("-")[:40]

    handoff_dir = build_dir.parent / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    zip_path = handoff_dir / f"{business_slug}-website.zip"

    readme_content = _build_readme(lead, domain)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Add README
        zf.writestr("README.md", readme_content)

        # Add all files from the build directory
        for file_path in sorted(build_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(build_dir)
                zf.write(file_path, arcname)
                log.debug("Added to zip: %s", arcname)

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    log.info("Handoff zip created: %s (%.1f MB)", zip_path, zip_size_mb)

    if zip_size_mb > 20:
        log.warning(
            "Zip file is %.1f MB — consider compressing images before delivery "
            "(Gmail attachment limit is 25MB; large zips should use a download link instead)",
            zip_size_mb,
        )

    return zip_path


# ── Email sender ──────────────────────────────────────────────────────────────

def _send_handoff_email(
    lead: dict,
    zip_path: Path,
    domain: str,
    dry_run: bool = False,
) -> bool:
    """Send the zip delivery email with the site attached (via Resend or SMTP fallback)."""
    to_email = lead.get("email")
    if not to_email:
        log.error("No email address for lead #%d — cannot send handoff.", lead["id"])
        return False

    owner = lead.get("owner_name") or "there"
    business = lead.get("business_name", "your business")

    subject = f"Your {business} website is ready — files inside"

    body = f"""Hi {owner},

Your website for {business} is complete and ready to go live.

I've attached everything you need as a zip file. The README inside explains how to upload it to your hosting in plain English — three different options depending on where you're hosting.

Domain: {domain if domain else '(set up your own domain and point it to the site folder)'}

If you run into any trouble uploading or have questions, just reply here and I'll help you through it.

Once you're live, let me know — I'd love to see it up. If you want us to handle hosting and updates going forward, the care plan is at {_CARE_PLAN_UPGRADE_URL} (starts at $75/mo, includes backups, updates, and priority support).

Thanks for working with {AGENCY_NAME} — it was a pleasure.

{AGENCY_OWNER}
{AGENCY_NAME}
{AGENCY_URL}

---
Payment methods: Stripe (via our secure portal), Venmo, or CashApp
"""

    if dry_run:
        log.info(
            "[DRY RUN] Would send handoff email:\n  To: %s\n  Subject: %s\n  Attachment: %s",
            to_email, subject, zip_path.name,
        )
        return True

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    attachment = None

    if zip_size_mb <= 20:
        attachment = [{"filename": zip_path.name, "content": zip_path.read_bytes()}]
    else:
        log.warning(
            "Zip is %.1f MB — too large to attach; sending without attachment.",
            zip_size_mb,
        )
        body = body.replace(
            "I've attached everything you need as a zip file.",
            "I've prepared your site files. They're too large to attach directly — "
            "I'll send you a secure download link separately.",
        )

    html = f"<div style='font-family:sans-serif;max-width:600px'>{body.replace(chr(10), '<br>')}</div>"

    ok = send_transactional(
        to_email=to_email,
        subject=subject,
        html=html,
        text=body,
        lead_id=lead["id"],
        log_to_crm=True,
        attachments=attachment,
    )

    if ok:
        log.info("Handoff email sent to %s (lead #%d, %s)", to_email, lead["id"], business)
    else:
        log.error("Failed to send handoff email to %s", to_email)
    return ok


# ── Public API ────────────────────────────────────────────────────────────────

def deliver_handoff(
    lead: dict,
    build_dir: Path,
    domain: str,
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Package the built site as a zip and email it to the client.

    Args:
        lead:      CRM lead dict
        build_dir: Path to the built site directory (data/builds/{lead_id}/)
        domain:    The client's domain string (for the README and email)
        dry_run:   If True, creates the zip but doesn't send the email

    Returns the zip Path on success, None on failure.
    """
    lead_id = lead["id"]

    if not build_dir.exists():
        log.error(
            "Build directory not found: %s — run site_builder first.",
            build_dir,
        )
        return None

    log.info(
        "Creating handoff zip for lead #%d (%s)...",
        lead_id, lead.get("business_name"),
    )

    zip_path = create_handoff_zip(lead, build_dir, domain)

    success = _send_handoff_email(lead, zip_path, domain, dry_run=dry_run)

    if success:
        update_lead_status(
            lead_id, "delivered",
            notes=f"Track B handoff — zip delivered to {lead.get('email')} | domain: {domain}",
        )
        log.info(
            "Handoff complete for lead #%d. Status → delivered.",
            lead_id,
        )
        return zip_path
    else:
        log.error("Handoff email failed for lead #%d", lead_id)
        return None
