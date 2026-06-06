"""
Mockup delivery — deploys the static HTML mockup to Netlify and emails
the prospect with a "free preview" link.

Deploy strategy
───────────────
1. POST the HTML file to Netlify's Deploy API (free tier, no account for
   the lead needed — just Steele's Netlify token).
2. Each lead gets a unique site slug: curbsite-{lead_id}-{slug}.netlify.app
3. If NETLIFY_ACCESS_TOKEN is not set, falls back to a localhost path with
   a warning — useful for dry-run / dev mode.

Email strategy
──────────────
- Short, personalized email: "I built you a free mockup — take a look"
- Includes a direct link to the Netlify preview
- GPT-4o-mini drafts the email body (not cached — each should feel fresh)
"""

import io
import json
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests

from src.config import (
    AGENCY_NAME, AGENCY_OWNER, AGENCY_URL,
    FROM_EMAIL, FROM_NAME, REPLY_TO,
    MODEL_DEFAULT,
)
from src.ai_client import chat
from src.crm.database import update_lead_status, log_outreach, get_conn
from src.outreach.email_sender import send_email

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Netlify deploy ────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:40]


def deploy_mockup_to_netlify(
    html_path: Path,
    lead_id: int,
    business_name: str,
    netlify_token: Optional[str] = None,
) -> Optional[str]:
    """
    Deploy index.html to Netlify. Returns the live URL or None on failure.

    Uses a zip-based deploy: POST /api/v1/sites/{site_id}/deploys
    with Content-Type: application/zip.
    """
    if not netlify_token:
        import os
        netlify_token = os.getenv("NETLIFY_ACCESS_TOKEN")

    if not netlify_token:
        log.warning(
            "NETLIFY_ACCESS_TOKEN not set — mockup will not be hosted. "
            "Set it in .env to enable live mockup previews."
        )
        return None

    headers = {
        "Authorization": f"Bearer {netlify_token}",
        "Content-Type": "application/json",
    }

    site_name = f"curbsite-{lead_id}-{_slugify(business_name)}"

    # Create or find the Netlify site
    try:
        create_resp = requests.post(
            "https://api.netlify.com/api/v1/sites",
            headers=headers,
            json={"name": site_name},
            timeout=15,
        )
        create_resp.raise_for_status()
        site = create_resp.json()
        site_id = site["id"]
        site_url = site.get("ssl_url") or site.get("url") or f"https://{site_name}.netlify.app"
        log.debug("Netlify site created: %s → %s", site_id, site_url)
    except requests.RequestException as exc:
        log.error("Failed to create Netlify site: %s", exc)
        return None

    # Build a zip of the HTML file
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(html_path, "index.html")
    zip_buf.seek(0)

    # Upload the zip as a deploy
    try:
        deploy_resp = requests.post(
            f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
            headers={
                "Authorization": f"Bearer {netlify_token}",
                "Content-Type": "application/zip",
            },
            data=zip_buf.read(),
            timeout=60,
        )
        deploy_resp.raise_for_status()
        deploy = deploy_resp.json()
        deploy_url = deploy.get("deploy_ssl_url") or deploy.get("deploy_url") or site_url
        log.info("Netlify deploy live: %s", deploy_url)
        return deploy_url
    except requests.RequestException as exc:
        log.error("Netlify deploy failed: %s", exc)
        return site_url  # site exists, deploy may still propagate


def _store_mockup(lead_id: int, html_path: Path, deploy_url: Optional[str]) -> None:
    """Upsert a row in the mockups table."""
    from datetime import datetime
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO mockups (lead_id, html_path, deploy_url, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(lead_id) DO UPDATE SET
                 html_path=excluded.html_path,
                 deploy_url=excluded.deploy_url,
                 created_at=excluded.created_at""",
            (lead_id, str(html_path), deploy_url, datetime.utcnow().isoformat()),
        )


# ── Email composition ─────────────────────────────────────────────────────────

_MOCKUP_EMAIL_SYSTEM = (
    "You are a friendly web designer who just built a free website mockup for a small "
    "business owner. Write a short, warm email letting them know their free mockup is ready. "
    "Rules: 3-5 sentences max. No bullet lists. Sound like a real person, not a bot. "
    "End with a CTA to click the link and reply with thoughts. "
    "Do NOT mention any price in this email. "
    "Output format ONLY:\n"
    "SUBJECT: <subject line>\n"
    "BODY:\n<email body>"
)


def _compose_mockup_email(lead: dict, preview_url: str) -> tuple[str, str]:
    business_name = lead.get("business_name", "your business")
    owner = lead.get("owner_name")
    greeting = f"Hi {owner}" if owner else "Hi there"
    niche = lead.get("niche", "business")
    city = lead.get("city", "")

    user = (
        f"Greeting: {greeting}\n"
        f"Business: {business_name} — a {niche} in {city}\n"
        f"My name: {AGENCY_OWNER} from {AGENCY_NAME}\n"
        f"Preview URL: {preview_url}\n\n"
        f"Tell them I took 10 minutes and built them a free mockup of what their new site "
        f"could look like. Give them the link and ask what they think."
    )

    raw = chat(
        messages=[
            {"role": "system", "content": _MOCKUP_EMAIL_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=MODEL_DEFAULT,
        max_tokens=300,
        temperature=0.65,
        operation="mockup_delivery_email",
        use_cache=False,
    )

    subject = f"Quick thing I built for {business_name}"
    body = raw

    if "SUBJECT:" in raw and "BODY:" in raw:
        try:
            s_part, b_part = raw.split("BODY:", 1)
            subject = s_part.replace("SUBJECT:", "").strip().split("\n")[0].strip()
            body = b_part.strip()
        except ValueError:
            pass

    # Guarantee the preview link is in the body
    if preview_url not in body:
        body += f"\n\nHere's the mockup: {preview_url}"

    return subject, body


# ── Public API ────────────────────────────────────────────────────────────────

def deliver_mockup(
    lead: dict,
    html_path: Path,
    dry_run: bool = False,
) -> Optional[str]:
    """
    Deploy mockup to Netlify and send the prospect an email with the preview link.

    Returns the deployed URL or None.
    Updates lead status to 'mockup_sent'.
    """
    lead_id = lead["id"]
    business_name = lead.get("business_name", "")
    prospect_email = lead.get("email")

    # Deploy to Netlify
    deploy_url = deploy_mockup_to_netlify(
        html_path=html_path,
        lead_id=lead_id,
        business_name=business_name,
    )

    if not deploy_url:
        log.warning("No deploy URL — mockup delivery aborted for lead #%d", lead_id)
        return None

    # Store in CRM
    _store_mockup(lead_id, html_path, deploy_url)

    # Compose and send email
    if not prospect_email:
        log.warning("No email for lead #%d — cannot deliver mockup", lead_id)
        return deploy_url

    subject, body = _compose_mockup_email(lead, deploy_url)

    success = send_email(
        lead_id=lead_id,
        to_email=prospect_email,
        subject=subject,
        body=body,
        dry_run=dry_run,
    )

    if success:
        update_lead_status(lead_id, "mockup_sent", notes=f"mockup_url={deploy_url}")
        log.info(
            "Mockup delivered to %s (%s): %s",
            business_name, prospect_email, deploy_url,
        )
    else:
        log.error("Failed to send mockup email for lead #%d", lead_id)

    return deploy_url
