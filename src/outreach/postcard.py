"""
Lob.com postcard sender for Curbsite lead outreach.
Sends a 4x6 postcard with QR code pointing to the business's personalized mockup site.
"""

import io
import base64
import logging
import time
from typing import Callable

import lob

from src.config import LOB_API_KEY, LOB_LIVE_MODE

lob.api_key = LOB_API_KEY

log = logging.getLogger(__name__)

# ── Postcard HTML templates ───────────────────────────────────────────────────

FRONT_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 6.25in; height: 4.25in;
    font-family: 'Inter', sans-serif;
    background: #0f0f0f;
    color: white;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.4in;
    overflow: hidden;
  }
  .left { flex: 1; padding-right: 0.3in; }
  .eyebrow {
    font-size: 11px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 12px;
  }
  h1 {
    font-size: 36px;
    font-weight: 900;
    line-height: 1.1;
    margin-bottom: 16px;
    color: white;
  }
  h1 span { color: #22c55e; }
  p {
    font-size: 13px;
    color: #aaa;
    line-height: 1.6;
    margin-bottom: 20px;
  }
  .domain { font-size: 12px; color: #666; letter-spacing: 0.05em; }
  .right {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }
  .qr-box {
    background: white;
    padding: 12px;
    border-radius: 8px;
  }
  .qr-box img { width: 1.4in; height: 1.4in; display: block; }
  .cta { font-size: 10px; color: #888; text-align: center; line-height: 1.4; }
</style>
</head>
<body>
  <div class="left">
    <div class="eyebrow">Your Free Website Preview</div>
    <h1>We built <span>{{business_name}}</span> a website.</h1>
    <p>Scan to see your custom site — no commitment, completely free to view.</p>
    <div class="domain">getcurbsite.co</div>
  </div>
  <div class="right">
    <div class="qr-box">
      <img src="{{qr_code_url}}" alt="QR Code">
    </div>
    <div class="cta">Scan to see<br>your free preview</div>
  </div>
</body>
</html>"""


def _make_qr_data_url(url: str) -> str:
    import qrcode
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


# ── Public API ────────────────────────────────────────────────────────────────

def send_postcard(lead: dict, mockup_url: str, dry_run: bool = not LOB_LIVE_MODE) -> dict:
    """
    Send a 4x6 postcard to a lead via Lob.
    Returns {'postcard_id': str, 'dry_run': bool, 'status': str}
    """
    business_name = lead.get("business_name") or lead.get("name") or "Your Business"

    if dry_run:
        log.info(
            "[DRY RUN] Would mail postcard to lead #%s (%s) at %s, %s %s %s",
            lead.get("id"), business_name,
            lead.get("address_line1", "?"), lead.get("city", "?"),
            lead.get("state", "?"), lead.get("zip_code", "?"),
        )
        return {"postcard_id": f"dry_run_{lead['id']}", "dry_run": True, "status": "test"}

    qr_data_url = _make_qr_data_url(mockup_url)
    front = (
        FRONT_HTML
        .replace("{{business_name}}", _escape_html(business_name))
        .replace("{{qr_code_url}}", qr_data_url)
    )

    postcard = lob.Postcard.create(
        description=f"Curbsite outreach - {business_name}",
        to={
            "name": business_name,
            "address_line1": lead["address_line1"],
            "address_city": lead["city"],
            "address_state": lead["state"],
            "address_zip": lead.get("zip_code", ""),
            "address_country": "US",
        },
        **{"from": {
            "name": "Steele Stout",
            "address_line1": "2717 Rockford Ln",
            "address_city": "Kokomo",
            "address_state": "IN",
            "address_zip": "46902",
            "address_country": "US",
        }},
        front=front,
        back="https://lob.com/postcardback",
        size="4x6",
    )

    log.info(
        "Postcard queued for lead #%s (%s): %s",
        lead.get("id"), business_name, postcard.id,
    )
    return {"postcard_id": postcard.id, "dry_run": False, "status": postcard.status}


def send_postcard_batch(
    leads: list,
    get_mockup_url: Callable[[dict], str],
    dry_run: bool = not LOB_LIVE_MODE,
) -> dict:
    """
    Send postcards to a batch of leads.
    get_mockup_url is a callable(lead) -> str.
    Returns summary dict.
    """
    results = {"sent": 0, "failed": 0, "dry_run": dry_run, "ids": []}
    for lead in leads:
        try:
            mockup_url = get_mockup_url(lead)
            result = send_postcard(lead, mockup_url, dry_run=dry_run)
            results["sent"] += 1
            results["ids"].append(result["postcard_id"])
        except Exception as exc:
            results["failed"] += 1
            log.error("Postcard failed for lead #%s: %s", lead.get("id"), exc)
        time.sleep(0.5)
    return results
