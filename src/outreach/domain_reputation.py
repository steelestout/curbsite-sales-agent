"""
Sending domain DNS reputation checker.

Verifies that SPF, DKIM, and DMARC are properly configured before any
campaign send. Logs clear warnings with remediation steps if records are missing.

See docs/EMAIL_SETUP.md for full setup instructions.

Usage:
    python -m src.outreach.domain_reputation mail.curbsite.co
    # or from code:
    from src.outreach.domain_reputation import warn_if_misconfigured
    ok = warn_if_misconfigured("mail.curbsite.co")
"""

import logging
import re
import subprocess
import sys
from typing import Optional

log = logging.getLogger(__name__)

try:
    import dns.resolver as _resolver
    _HAS_DNSPYTHON = True
except ImportError:
    _HAS_DNSPYTHON = False


# ── DNS lookup ─────────────────────────────────────────────────────────────────

def _txt_records(domain: str) -> list[str]:
    """Return all TXT record strings for a domain."""
    if _HAS_DNSPYTHON:
        try:
            answers = _resolver.resolve(domain, "TXT")
            out = []
            for rdata in answers:
                for chunk in rdata.strings:
                    out.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
            return out
        except Exception:
            return []

    # Fallback: nslookup (Windows-compatible)
    try:
        result = subprocess.run(
            ["nslookup", "-type=TXT", domain],
            capture_output=True, text=True, timeout=10,
        )
        return re.findall(r'"([^"]+)"', result.stdout)
    except Exception:
        return []


# ── Per-record checks ─────────────────────────────────────────────────────────

def check_spf(domain: str) -> dict:
    """Check for a valid SPF TXT record on the domain."""
    records = _txt_records(domain)
    spf = [r for r in records if r.strip().startswith("v=spf1")]
    if spf:
        return {"ok": True, "record": spf[0]}
    return {
        "ok": False,
        "record": None,
        "advice": (
            f"Add a TXT record on {domain}:\n"
            "  v=spf1 include:_spf.google.com ~all\n"
            "  (Use 'include:sendgrid.net ~all' instead if you send via SendGrid)"
        ),
    }


def check_dmarc(domain: str) -> dict:
    """Check for a valid DMARC TXT record at _dmarc.<domain>."""
    dmarc_host = f"_dmarc.{domain}"
    records = _txt_records(dmarc_host)
    dmarc = [r for r in records if r.strip().startswith("v=DMARC1")]
    if dmarc:
        return {"ok": True, "record": dmarc[0]}
    return {
        "ok": False,
        "record": None,
        "advice": (
            f"Add a TXT record on _dmarc.{domain}:\n"
            "  v=DMARC1; p=quarantine; rua=mailto:steele.stout@gmail.com\n"
            "  (Start with p=none while testing, then switch to p=quarantine)"
        ),
    }


def check_dkim(domain: str, selector: str = "google") -> dict:
    """
    Check for a DKIM TXT record at <selector>._domainkey.<domain>.
    Default selector is 'google' (Google Workspace). Use 's1' for SendGrid.
    """
    dkim_host = f"{selector}._domainkey.{domain}"
    records = _txt_records(dkim_host)
    dkim = [r for r in records if "v=DKIM1" in r or "k=rsa" in r]
    if dkim:
        return {"ok": True, "record": dkim[0][:80] + ("..." if len(dkim[0]) > 80 else "")}
    return {
        "ok": False,
        "record": None,
        "advice": (
            f"Generate your DKIM key in Google Workspace Admin:\n"
            f"  Admin Console → Apps → Google Workspace → Gmail → Authenticate email\n"
            f"  Select domain: {domain}, selector prefix: {selector}\n"
            f"  Add the generated TXT record at {dkim_host}"
        ),
    }


# ── Main checker ──────────────────────────────────────────────────────────────

def check_domain(domain: str, dkim_selector: str = "google") -> dict:
    """
    Run SPF, DKIM, and DMARC checks for a sending domain.
    Returns a dict with per-check results and an overall 'ok' flag.
    """
    spf = check_spf(domain)
    dkim = check_dkim(domain, dkim_selector)
    dmarc = check_dmarc(domain)

    return {
        "domain": domain,
        "ok": spf["ok"] and dkim["ok"] and dmarc["ok"],
        "spf": spf,
        "dkim": dkim,
        "dmarc": dmarc,
    }


def warn_if_misconfigured(domain: str, dkim_selector: str = "google") -> bool:
    """
    Check DNS records and log warnings with remediation steps.
    Returns True if all records are correct, False if any are missing.
    Call this at startup before beginning any outreach campaign.
    """
    result = check_domain(domain, dkim_selector)

    if result["ok"]:
        log.info("Domain %s: SPF ✓  DKIM ✓  DMARC ✓ — good to send", domain)
        return True

    log.error(
        "Domain %s has deliverability gaps — emails may land in spam! "
        "Fix these records before sending cold outreach.",
        domain,
    )
    for key in ("spf", "dkim", "dmarc"):
        check = result[key]
        if not check["ok"]:
            log.error("  %s MISSING:\n%s", key.upper(), check.get("advice", ""))

    return False


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    domain_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    selector_arg = sys.argv[2] if len(sys.argv) > 2 else "google"

    if not domain_arg:
        print("Usage: python -m src.outreach.domain_reputation <domain> [dkim_selector]")
        print("Example: python -m src.outreach.domain_reputation mail.curbsite.co google")
        sys.exit(1)

    result = check_domain(domain_arg, selector_arg)
    print(f"\nDomain: {result['domain']}")
    for key in ("spf", "dkim", "dmarc"):
        c = result[key]
        status = "OK" if c["ok"] else "MISSING"
        record_info = c.get("record") or c.get("advice", "")
        print(f"  {key.upper():6s}: {status}")
        if not c["ok"]:
            print(f"         Fix: {record_info}")

    print(f"\nOverall: {'ALL CLEAR' if result['ok'] else 'ACTION REQUIRED'}")
    sys.exit(0 if result["ok"] else 1)
