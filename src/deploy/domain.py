"""
Domain purchase — buys a domain via Namecheap API.

Flow
────
1. Derive candidate domain names from the business name
2. Check availability (Namecheap XML API)
3. Purchase the first available option
4. Log purchase to the 'domains' CRM table
5. Return the registered domain name

Fallback: if NAMECHEAP_API_KEY is not set or purchase fails,
logs a manual TODO and returns None so the pipeline can continue
with a placeholder domain.

Namecheap Sandbox
─────────────────
Set NAMECHEAP_SANDBOX=1 in .env to use the sandbox API
(sandbox.namecheap.com) for testing without real purchases.
"""

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional

import requests

from src.crm.database import get_conn, update_lead_status

log = logging.getLogger(__name__)

_NAMECHEAP_API_KEY: str = os.getenv("NAMECHEAP_API_KEY", "")
_NAMECHEAP_USER: str = os.getenv("NAMECHEAP_USERNAME", "")
_NAMECHEAP_CLIENT_IP: str = os.getenv("NAMECHEAP_CLIENT_IP", "")
_SANDBOX: bool = os.getenv("NAMECHEAP_SANDBOX", "0") == "1"

_NC_BASE = (
    "https://api.sandbox.namecheap.com/xml.response"
    if _SANDBOX
    else "https://api.namecheap.com/xml.response"
)

_REGISTRANT = {
    "RegistrantFirstName": os.getenv("REGISTRANT_FIRST_NAME", "Steele"),
    "RegistrantLastName": os.getenv("REGISTRANT_LAST_NAME", "Stout"),
    "RegistrantAddress1": os.getenv("REGISTRANT_ADDRESS", "123 Main St"),
    "RegistrantCity": os.getenv("REGISTRANT_CITY", "Kokomo"),
    "RegistrantStateProvince": os.getenv("REGISTRANT_STATE", "IN"),
    "RegistrantPostalCode": os.getenv("REGISTRANT_ZIP", "46902"),
    "RegistrantCountry": os.getenv("REGISTRANT_COUNTRY", "US"),
    "RegistrantPhone": os.getenv("REGISTRANT_PHONE", "+1.5555555555"),
    "RegistrantEmailAddress": os.getenv("REGISTRANT_EMAIL", "steele.stout@gmail.com"),
}


# ── Domain candidate generation ───────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", "-", text.strip())


def _candidates(business_name: str, city: str = "") -> list[str]:
    """Generate 3–5 domain candidates from a business name."""
    slug = _slugify(business_name)
    city_slug = _slugify(city)

    options = [
        f"{slug}.com",
        f"{slug}.net",
        f"{slug}{city_slug}.com" if city_slug else None,
        f"{city_slug}{slug}.com" if city_slug else None,
        f"get{slug}.com",
    ]
    return [d for d in options if d and len(d) <= 63]


# ── Namecheap API helpers ─────────────────────────────────────────────────────

def _nc_params(command: str, **extras) -> dict:
    params = {
        "ApiUser": _NAMECHEAP_USER,
        "ApiKey": _NAMECHEAP_API_KEY,
        "UserName": _NAMECHEAP_USER,
        "ClientIp": _NAMECHEAP_CLIENT_IP,
        "Command": command,
    }
    params.update(extras)
    return params


def _nc_call(command: str, **extras) -> Optional[ET.Element]:
    """Make a Namecheap API call and return the root XML element, or None on error."""
    if not _NAMECHEAP_API_KEY or not _NAMECHEAP_USER:
        log.warning("NAMECHEAP_API_KEY / NAMECHEAP_USERNAME not set — skipping Namecheap call")
        return None

    params = _nc_params(command, **extras)
    try:
        resp = requests.get(_NC_BASE, params=params, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        status = root.attrib.get("Status", "")
        if status == "ERROR":
            errors = root.findall(".//{http://api.namecheap.com/xml.response}Error")
            for e in errors:
                log.error("Namecheap error: %s", e.text)
            return None
        return root
    except Exception as exc:
        log.error("Namecheap API call failed (%s): %s", command, exc)
        return None


def check_availability(domains: list[str]) -> dict[str, bool]:
    """
    Check availability for a list of domain names.
    Returns {domain: available} dict. Available = True means the domain is purchasable.
    """
    domain_list = ",".join(d.replace(".com", "") for d in domains if d.endswith(".com"))
    root = _nc_call("namecheap.domains.check", DomainList=domain_list)

    if root is None:
        return {}

    result = {}
    ns = "{http://api.namecheap.com/xml.response}"
    for dc in root.findall(f".//{ns}DomainCheckResult"):
        name = dc.attrib.get("Domain", "") + ".com"
        available = dc.attrib.get("Available", "false").lower() == "true"
        result[name] = available

    return result


def purchase_domain(domain: str) -> bool:
    """
    Purchase a domain on Namecheap. Returns True on success.
    Uses registrant info from .env / _REGISTRANT defaults.
    """
    sld, tld = domain.rsplit(".", 1)

    params = {
        "DomainName": domain,
        "Years": "1",
        "SLD": sld,
        "TLD": tld,
        **_REGISTRANT,
        # Tech/billing/admin contacts — same as registrant
        **{k.replace("Registrant", "Tech"): v for k, v in _REGISTRANT.items()},
        **{k.replace("Registrant", "Admin"): v for k, v in _REGISTRANT.items()},
        **{k.replace("Registrant", "AuxBilling"): v for k, v in _REGISTRANT.items()},
    }

    root = _nc_call("namecheap.domains.create", **params)
    if root is None:
        return False

    ns = "{http://api.namecheap.com/xml.response}"
    result = root.find(f".//{ns}DomainCreateResult")
    if result is None:
        return False

    registered = result.attrib.get("Registered", "false").lower() == "true"
    if registered:
        log.info("Domain purchased: %s (%s)", domain, "SANDBOX" if _SANDBOX else "LIVE")
    return registered


# ── CRM persistence ───────────────────────────────────────────────────────────

def _store_domain(lead_id: int, domain: str, registrar: str = "namecheap") -> None:
    now = datetime.utcnow()
    expiry = (now + timedelta(days=365)).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO domains (lead_id, domain_name, registrar, purchase_date, expiry_date)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(lead_id) DO UPDATE SET
                 domain_name=excluded.domain_name,
                 registrar=excluded.registrar,
                 purchase_date=excluded.purchase_date,
                 expiry_date=excluded.expiry_date""",
            (lead_id, domain, registrar, now.isoformat(), expiry),
        )


# ── Public API ────────────────────────────────────────────────────────────────

def acquire_domain(lead: dict, preferred: Optional[str] = None) -> Optional[str]:
    """
    Find and purchase the best available domain for a client.

    Args:
        lead:      CRM lead dict
        preferred: If set, try this domain first before auto-generating candidates

    Returns the purchased domain name, or None if Namecheap is not configured
    or all options are unavailable.
    """
    lead_id = lead["id"]
    business_name = lead.get("business_name", "")
    city = lead.get("city", "")

    if not _NAMECHEAP_API_KEY:
        log.warning(
            "NAMECHEAP_API_KEY not set. Domain purchase skipped for lead #%d.\n"
            "TODO: Manually purchase a domain for '%s' and set it in the CRM.",
            lead_id, business_name,
        )
        return None

    candidates = _candidates(business_name, city)
    if preferred:
        candidates.insert(0, preferred)

    log.info("Checking domain availability for: %s", candidates)
    availability = check_availability(candidates)

    chosen = None
    for domain in candidates:
        if availability.get(domain):
            chosen = domain
            break

    if not chosen:
        log.warning(
            "No available domains found for '%s'. Candidates checked: %s",
            business_name, candidates,
        )
        return None

    log.info("Purchasing domain: %s", chosen)
    success = purchase_domain(chosen)
    if not success:
        log.error("Domain purchase failed for %s", chosen)
        return None

    _store_domain(lead_id, chosen)
    update_lead_status(
        lead_id, "domain_purchased",
        notes=f"domain={chosen} | registrar=namecheap | sandbox={_SANDBOX}",
    )
    log.info("Domain registered: %s → lead #%d", chosen, lead_id)
    return chosen
