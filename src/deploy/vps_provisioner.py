"""
VPS provisioner — Track A (clients with maintenance package).

Provisions a dedicated VPS for a client site via Hetzner Cloud API.

Why Hetzner?
────────────
- Cheapest price/performance among major providers
- Excellent REST API (well-documented, reliable)
- US datacenter in Ashburn, VA (good latency for Midwest clients)
- Standard CX22: 2 vCPU, 4GB RAM, 40GB SSD ≈ $5/mo
- Performance CX32: 4 vCPU, 8GB RAM, 80GB SSD ≈ $9/mo

Compared: Vultr $6/$12, DigitalOcean $6/$12 — Hetzner wins at both tiers.

VPS Size Rules
──────────────
Standard (CX22): Salons, contractors, auto shops, fitness, photographers
  — brochure + booking sites, low concurrent load
  — ~$5/mo — comfortably covered by $75/mo care plan

Performance (CX32): Restaurants with online ordering, any mid/top tier
  with Square/Toast ordering under lunch/dinner rush load
  — ~$9/mo — covered by $100-125/mo care plan

Auto-select logic:
  niche == restaurant AND tier >= mid  → Performance
  everything else                      → Standard

Deployment flow
───────────────
1. Create Hetzner server via API (cloud-init handles all setup)
2. cloud-init installs Docker, Docker Compose, Traefik
3. Upload site files via SSH/SFTP (reuses host.py logic)
4. Start Docker container with Traefik labels
5. Update DNS at Namecheap → VPS IP

.env vars
─────────
  HETZNER_API_TOKEN     Hetzner Cloud API token (project-level)
  HETZNER_DATACENTER    e.g. ash (Ashburn VA) or nbg1 (Nuremberg DE)
  HETZNER_SSH_KEY_NAME  Name of SSH key uploaded to Hetzner project

Fallback: if HETZNER_API_TOKEN is not set, logs a TODO and returns None
so the pipeline continues — Steele can provision manually.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

from src.crm.database import update_lead_status, get_conn

log = logging.getLogger(__name__)

_HETZNER_TOKEN: str = os.getenv("HETZNER_API_TOKEN", "")
_DATACENTER: str = os.getenv("HETZNER_DATACENTER", "ash")        # Ashburn, VA
_SSH_KEY_NAME: str = os.getenv("HETZNER_SSH_KEY_NAME", "curbsite")
_HETZNER_BASE = "https://api.hetzner.cloud/v1"

# ── Server specs ──────────────────────────────────────────────────────────────

_SERVER_TYPES = {
    "standard":    {"type": "cx22", "ram": 4,  "cpu": 2, "disk": 40, "price_mo": 5},
    "performance": {"type": "cx32", "ram": 8,  "cpu": 4, "disk": 80, "price_mo": 9},
}

_CARE_PLAN_PRICES = {75: "standard", 100: "standard", 125: "performance"}

# Restaurant + mid/top → performance VPS
_PERFORMANCE_NICHES = {"restaurant", "cafe", "food"}


def _select_server_type(lead: dict) -> str:
    niche = (lead.get("niche") or "").lower()
    tier = (lead.get("tier") or "entry").lower()
    if any(n in niche for n in _PERFORMANCE_NICHES) and tier in ("mid", "top"):
        return "performance"
    return "standard"


# ── Cloud-init setup script ───────────────────────────────────────────────────

_CLOUD_INIT = """\
#cloud-config
package_update: true
packages:
  - docker.io
  - docker-compose-plugin
  - curl
  - ufw

runcmd:
  # Docker socket group
  - usermod -aG docker ubuntu || true
  # Firewall: allow SSH, HTTP, HTTPS
  - ufw allow 22/tcp
  - ufw allow 80/tcp
  - ufw allow 443/tcp
  - ufw --force enable
  # Create Traefik network
  - docker network create traefik_net || true
  # Start Traefik
  - |
    docker run -d \
      --name traefik \
      --network traefik_net \
      -p 80:80 -p 443:443 \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v /opt/traefik/acme.json:/acme.json \
      traefik:v2.11 \
      --api.insecure=false \
      --providers.docker=true \
      --providers.docker.exposedbydefault=false \
      --entrypoints.web.address=:80 \
      --entrypoints.web.http.redirections.entrypoint.to=websecure \
      --entrypoints.websecure.address=:443 \
      --certificatesresolvers.letsencrypt.acme.tlschallenge=true \
      --certificatesresolvers.letsencrypt.acme.email=steele.stout@gmail.com \
      --certificatesresolvers.letsencrypt.acme.storage=/acme.json
  # Create acme.json with right permissions
  - mkdir -p /opt/traefik && touch /opt/traefik/acme.json && chmod 600 /opt/traefik/acme.json
  # Create site root
  - mkdir -p /var/www
"""


# ── Hetzner API helpers ───────────────────────────────────────────────────────

def _hc(method: str, path: str, **kwargs) -> Optional[dict]:
    """Make a Hetzner Cloud API call. Returns JSON response or None on error."""
    if not _HETZNER_TOKEN:
        return None
    headers = {
        "Authorization": f"Bearer {_HETZNER_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.request(
            method,
            f"{_HETZNER_BASE}{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.error("Hetzner API %s %s failed: %s", method, path, exc)
        if hasattr(exc, "response") and exc.response is not None:
            log.error("Response: %s", exc.response.text[:300])
        return None


def _get_ssh_key_id() -> Optional[int]:
    """Get the ID of the configured SSH key in the Hetzner project."""
    resp = _hc("GET", "/ssh_keys")
    if not resp:
        return None
    for key in resp.get("ssh_keys", []):
        if key.get("name") == _SSH_KEY_NAME:
            return key["id"]
    log.warning(
        "SSH key '%s' not found in Hetzner project. "
        "Upload your public key at: https://console.hetzner.cloud → SSH Keys",
        _SSH_KEY_NAME,
    )
    return None


def _wait_for_server_ready(server_id: int, max_wait: int = 180) -> Optional[str]:
    """Poll until server status = 'running'. Returns the public IPv4 address."""
    for _ in range(max_wait // 10):
        resp = _hc("GET", f"/servers/{server_id}")
        if not resp:
            break
        server = resp.get("server", {})
        status = server.get("status")
        if status == "running":
            ip = server.get("public_net", {}).get("ipv4", {}).get("ip")
            log.info("Server #%d is running at %s", server_id, ip)
            return ip
        log.debug("Server #%d status: %s — waiting...", server_id, status)
        time.sleep(10)
    return None


def _store_vps(lead_id: int, server_id: int, ip: str, server_type: str, domain: str) -> None:
    specs = _SERVER_TYPES[server_type]
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO vps_instances
               (lead_id, hetzner_server_id, ip, server_type, domain, monthly_cost, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(lead_id) DO UPDATE SET
                 hetzner_server_id=excluded.hetzner_server_id,
                 ip=excluded.ip, server_type=excluded.server_type,
                 domain=excluded.domain, monthly_cost=excluded.monthly_cost""",
            (lead_id, server_id, ip, server_type, domain, specs["price_mo"]),
        )


# ── Public API ────────────────────────────────────────────────────────────────

def provision_vps(lead: dict, domain: str) -> Optional[str]:
    """
    Provision a new Hetzner VPS for a client site.

    Args:
        lead:   CRM lead dict
        domain: The client's registered domain (for server naming + Traefik config)

    Returns the server's public IP, or None if provisioning failed.
    """
    lead_id = lead["id"]

    if not _HETZNER_TOKEN:
        log.warning(
            "HETZNER_API_TOKEN not set. VPS provisioning skipped for lead #%d.\n"
            "TODO: Manually provision a VPS for '%s' (%s) and add its IP to the CRM.",
            lead_id, lead.get("business_name"), domain,
        )
        return None

    server_type_key = _select_server_type(lead)
    server_type = _SERVER_TYPES[server_type_key]["type"]
    specs = _SERVER_TYPES[server_type_key]

    log.info(
        "Provisioning %s VPS (%s: %d vCPU, %dGB RAM, %dGB SSD ~$%d/mo) for %s (%s)",
        server_type_key, server_type, specs["cpu"], specs["ram"],
        specs["disk"], specs["price_mo"],
        lead.get("business_name"), domain,
    )

    # Get SSH key ID
    ssh_key_id = _get_ssh_key_id()

    # Build server name (Hetzner requires lowercase, max 63 chars)
    server_name = domain.replace(".", "-")[:63].lower()

    # Create the server
    payload = {
        "name": server_name,
        "server_type": server_type,
        "image": "ubuntu-22.04",
        "datacenter": _DATACENTER,
        "user_data": _CLOUD_INIT,
        "labels": {
            "client": str(lead_id),
            "domain": domain,
            "managed_by": "curbsite",
        },
    }
    if ssh_key_id:
        payload["ssh_keys"] = [ssh_key_id]

    resp = _hc("POST", "/servers", json=payload)
    if not resp:
        log.error("Failed to create Hetzner server for lead #%d", lead_id)
        return None

    server_id = resp["server"]["id"]
    log.info("Server created: ID=%d, name=%s. Waiting for it to start...", server_id, server_name)

    # Wait for the server to be running
    ip = _wait_for_server_ready(server_id)
    if not ip:
        log.error("Server #%d never reached running status", server_id)
        return None

    # Give cloud-init time to finish (Docker install takes ~2-3 min)
    log.info("Server is up at %s. Waiting 120s for cloud-init to complete...", ip)
    time.sleep(120)

    # Store in CRM
    _store_vps(lead_id, server_id, ip, server_type_key, domain)
    update_lead_status(
        lead_id, "vps_provisioned",
        notes=f"hetzner_id={server_id} | ip={ip} | type={server_type_key} | domain={domain}",
    )

    log.info("VPS provisioned for lead #%d: %s (%s)", lead_id, ip, domain)
    return ip


def deprovision_vps(lead_id: int) -> bool:
    """
    Delete a client's VPS when their contract ends.
    WARNING: This permanently deletes the server and all data.
    Only call after confirming client has been offboarded.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT hetzner_server_id, domain FROM vps_instances WHERE lead_id=?",
            (lead_id,),
        ).fetchone()

    if not row:
        log.warning("No VPS found for lead #%d", lead_id)
        return False

    server_id = row["hetzner_server_id"]
    domain = row["domain"]
    log.warning(
        "DELETING VPS #%d for lead #%d (domain: %s). This is irreversible.",
        server_id, lead_id, domain,
    )

    resp = _hc("DELETE", f"/servers/{server_id}")
    if resp is None:
        log.error("Failed to delete server #%d", server_id)
        return False

    with get_conn() as conn:
        conn.execute("DELETE FROM vps_instances WHERE lead_id=?", (lead_id,))

    log.info("VPS deleted for lead #%d", lead_id)
    return True
