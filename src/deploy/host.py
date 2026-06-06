"""
Hostinger VPS deployment — uploads the built site and configures Traefik.

Deployment flow
───────────────
1. SSH into the Hostinger VPS (paramiko)
2. Create /var/www/{domain}/ on the server
3. Upload the built site files via SFTP
4. Write docker-compose.yml with Traefik labels
5. Run: docker-compose pull && docker-compose up -d --build
6. Update Namecheap DNS to point the domain → VPS IP

Prerequisites on the VPS (one-time setup by Steele)
────────────────────────────────────────────────────
- Docker + Docker Compose installed
- Traefik running as a reverse proxy (connected to 'traefik_net' network)
- Traefik configured for Let's Encrypt (certresolver=letsencrypt)
- SSH key in ~/.ssh/ for passwordless login

.env vars needed
────────────────
  HOSTINGER_VPS_HOST      VPS IP or hostname
  HOSTINGER_VPS_USER      SSH user (e.g. 'root' or 'steele')
  HOSTINGER_VPS_KEY_PATH  Path to private SSH key (default: ~/.ssh/id_rsa)
  HOSTINGER_VPS_IP        Public IP of the VPS (for DNS records)
  NAMECHEAP_API_KEY       For updating DNS
  NAMECHEAP_USERNAME
  NAMECHEAP_CLIENT_IP
"""

import logging
import os
import stat
import time
from pathlib import Path
from typing import Optional

from src.crm.database import update_lead_status

log = logging.getLogger(__name__)

_VPS_HOST: str = os.getenv("HOSTINGER_VPS_HOST", "")
_VPS_USER: str = os.getenv("HOSTINGER_VPS_USER", "root")
_VPS_KEY: str = os.getenv("HOSTINGER_VPS_KEY_PATH", str(Path.home() / ".ssh" / "id_rsa"))
_VPS_IP: str = os.getenv("HOSTINGER_VPS_IP", "")
_DEPLOY_ROOT: str = os.getenv("VPS_DEPLOY_ROOT", "/var/www")


# ── SSH / SFTP helpers ────────────────────────────────────────────────────────

def _get_ssh_client():
    """Return a connected paramiko SSHClient, or raise if paramiko not installed."""
    try:
        import paramiko
    except ImportError:
        raise RuntimeError(
            "paramiko is required for VPS deployment. Install it: pip install paramiko"
        )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=_VPS_HOST,
        username=_VPS_USER,
        key_filename=_VPS_KEY,
        timeout=30,
    )
    return client


def _run(ssh, cmd: str) -> tuple[str, str, int]:
    """Run a remote command. Returns (stdout, stderr, exit_code)."""
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    if code != 0:
        log.warning("Remote command exited %d: %s\nstderr: %s", code, cmd, err[:200])
    return out, err, code


def _sftp_upload_dir(sftp, local_dir: Path, remote_dir: str) -> None:
    """Recursively upload a local directory to a remote path via SFTP."""
    try:
        sftp.mkdir(remote_dir)
    except OSError:
        pass  # Already exists

    for item in local_dir.iterdir():
        remote_path = f"{remote_dir}/{item.name}"
        if item.is_dir():
            _sftp_upload_dir(sftp, item, remote_path)
        else:
            sftp.put(str(item), remote_path)
            log.debug("Uploaded: %s → %s", item.name, remote_path)


# ── DNS update ────────────────────────────────────────────────────────────────

def _update_dns(domain: str, vps_ip: str) -> bool:
    """
    Update Namecheap DNS to point the domain's A record to the VPS IP.
    Returns True on success.
    """
    import xml.etree.ElementTree as ET
    import requests

    nc_key = os.getenv("NAMECHEAP_API_KEY", "")
    nc_user = os.getenv("NAMECHEAP_USERNAME", "")
    nc_ip = os.getenv("NAMECHEAP_CLIENT_IP", "")
    sandbox = os.getenv("NAMECHEAP_SANDBOX", "0") == "1"

    if not nc_key:
        log.warning("NAMECHEAP_API_KEY not set — DNS update skipped. Set manually.")
        return False

    base = (
        "https://api.sandbox.namecheap.com/xml.response"
        if sandbox
        else "https://api.namecheap.com/xml.response"
    )

    sld, tld = domain.rsplit(".", 1)

    params = {
        "ApiUser": nc_user,
        "ApiKey": nc_key,
        "UserName": nc_user,
        "ClientIp": nc_ip,
        "Command": "namecheap.domains.dns.setHosts",
        "SLD": sld,
        "TLD": tld,
        "HostName1": "@",
        "RecordType1": "A",
        "Address1": vps_ip,
        "TTL1": "300",
        "HostName2": "www",
        "RecordType2": "CNAME",
        "Address2": f"{domain}.",
        "TTL2": "300",
    }

    try:
        resp = requests.get(base, params=params, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        status = root.attrib.get("Status", "")
        if status == "OK":
            log.info("DNS updated: %s → %s", domain, vps_ip)
            return True
        else:
            ns = "{http://api.namecheap.com/xml.response}"
            errors = [e.text for e in root.findall(f".//{ns}Error")]
            log.error("Namecheap DNS update failed: %s", errors)
            return False
    except Exception as exc:
        log.error("DNS update exception: %s", exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def deploy_to_vps(
    lead: dict,
    build_dir: Path,
    domain: str,
    dry_run: bool = False,
) -> bool:
    """
    Deploy a built site to the Hostinger VPS.

    1. Upload files via SFTP
    2. Run docker-compose up -d --build on the VPS
    3. Update DNS at Namecheap

    Returns True if deployment succeeded.
    """
    lead_id = lead["id"]

    if not _VPS_HOST:
        log.warning(
            "HOSTINGER_VPS_HOST not set. Deployment skipped for lead #%d.\n"
            "Configure VPS settings in .env to enable automated deployment.",
            lead_id,
        )
        return False

    if dry_run:
        log.info("[DRY RUN] Would deploy %s → %s@%s:/var/www/%s", build_dir, _VPS_USER, _VPS_HOST, domain)
        return True

    remote_site_dir = f"{_DEPLOY_ROOT}/{domain}"

    try:
        ssh = _get_ssh_client()
    except Exception as exc:
        log.error("SSH connection failed: %s", exc)
        return False

    try:
        sftp = ssh.open_sftp()

        # Create remote directory
        _run(ssh, f"mkdir -p {remote_site_dir}")
        log.info("Uploading site files to %s@%s:%s ...", _VPS_USER, _VPS_HOST, remote_site_dir)

        # Upload all build files
        _sftp_upload_dir(sftp, build_dir, remote_site_dir)
        sftp.close()

        # Start the Docker container
        log.info("Starting Docker container for %s ...", domain)
        out, err, code = _run(
            ssh,
            f"cd {remote_site_dir} && docker-compose up -d --build 2>&1"
        )
        if code != 0:
            log.error("docker-compose failed for %s:\n%s", domain, err)
            return False
        log.info("Docker container started: %s", out[:200])

        # Update DNS
        if _VPS_IP:
            _update_dns(domain, _VPS_IP)
        else:
            log.warning("HOSTINGER_VPS_IP not set — DNS update skipped. Update manually.")

    except Exception as exc:
        log.error("Deployment failed for lead #%d: %s", lead_id, exc)
        return False
    finally:
        ssh.close()

    update_lead_status(
        lead_id, "deployed",
        notes=f"domain={domain} | vps={_VPS_HOST} | dir={remote_site_dir}",
    )
    log.info("Deployed: https://%s (lead #%d)", domain, lead_id)
    return True
