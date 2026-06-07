"""
Portal sync — downloads client-uploaded assets from curbsite.co/crm.

Authentication
──────────────
Uses NextAuth.js credentials provider to log in as Steele (admin role),
then calls the portal API to list projects and download all uploaded files.

Login endpoint: POST https://curbsite.co/api/auth/callback/credentials
Projects API:   GET  https://curbsite.co/api/projects?clientId={id}
Files are stored at: https://curbsite.co/uploads/{projectId}/{filename}

If CURBSITE_CRM_API_KEY is set, we bypass the session login and use it
as a Bearer token instead — cleaner if Steele ever adds an API key auth
endpoint to the portal.

Output
──────
data/clients/{lead_id}/assets/
  ├── logo.*
  ├── photos/
  │   ├── hero.jpg
  │   └── ...
  └── documents/
      └── menu.pdf

Returns a manifest dict describing what was downloaded.

TODO: If the portal exposes a proper REST API with token auth, swap the
session-cookie approach for:
  headers = {"Authorization": f"Bearer {CURBSITE_CRM_API_KEY}"}
"""

import logging
import mimetypes
import os
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_CLIENTS_DIR = _ROOT / "data" / "clients"
_CLIENTS_DIR.mkdir(parents=True, exist_ok=True)

_PORTAL_BASE: str = os.getenv("CURBSITE_PORTAL_URL", "https://curbsite.co")
_OWNER_EMAIL: str = os.getenv("CURBSITE_OWNER_EMAIL", "")
_OWNER_PASS: str = os.getenv("CURBSITE_OWNER_PASSWORD", "")
_CRM_API_KEY: str = os.getenv("CURBSITE_CRM_API_KEY", "")


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_session() -> Optional[requests.Session]:
    """
    Log in to curbsite.co as Steele (admin) and return an authenticated
    requests.Session. Returns None if credentials are missing or login fails.
    """
    if not _OWNER_EMAIL or not _OWNER_PASS:
        log.warning(
            "CURBSITE_OWNER_EMAIL / CURBSITE_OWNER_PASSWORD not set. "
            "Portal sync will not work without credentials."
        )
        return None

    session = requests.Session()
    session.headers["User-Agent"] = "CurbsiteAgent/1.0"

    # Step 1: Get CSRF token from NextAuth
    try:
        csrf_resp = session.get(
            f"{_PORTAL_BASE}/api/auth/csrf",
            timeout=15,
        )
        csrf_resp.raise_for_status()
        csrf_token = csrf_resp.json().get("csrfToken", "")
    except Exception as exc:
        log.error("Failed to get CSRF token: %s", exc)
        return None

    # Step 2: Submit credentials
    try:
        login_resp = session.post(
            f"{_PORTAL_BASE}/api/auth/callback/credentials",
            data={
                "csrfToken": csrf_token,
                "email": _OWNER_EMAIL,
                "password": _OWNER_PASS,
                "redirect": "false",
                "callbackUrl": f"{_PORTAL_BASE}/crm",
                "json": "true",
            },
            timeout=15,
            allow_redirects=True,
        )
        # NextAuth returns a redirect or a JSON with url on success
        if login_resp.status_code not in (200, 302):
            log.error("Login failed: HTTP %d", login_resp.status_code)
            return None

        # Verify we got a session cookie
        if "next-auth.session-token" not in session.cookies and \
           "__Secure-next-auth.session-token" not in session.cookies:
            log.warning("Login may have failed — no session cookie received")

        log.debug("Portal login successful as %s", _OWNER_EMAIL)
        return session

    except Exception as exc:
        log.error("Login request failed: %s", exc)
        return None


def _api_headers() -> dict:
    """Return auth headers — API key if available, otherwise rely on session cookie."""
    if _CRM_API_KEY:
        return {"Authorization": f"Bearer {_CRM_API_KEY}"}
    return {}


# ── Project + file discovery ───────────────────────────────────────────────────

def _find_client_id(session: requests.Session, email: str) -> Optional[str]:
    """Look up the portal clientId by email address."""
    try:
        resp = session.get(
            f"{_PORTAL_BASE}/api/clients",
            headers=_api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        clients = resp.json()
        for client in clients:
            if (client.get("email") or "").lower() == email.lower():
                return client.get("id")
        log.warning("Client with email %s not found in portal", email)
        return None
    except Exception as exc:
        log.error("Failed to list portal clients: %s", exc)
        return None


def _list_projects(session: requests.Session, client_id: str) -> list[dict]:
    """Get all projects for a client, with their uploaded files."""
    try:
        resp = session.get(
            f"{_PORTAL_BASE}/api/projects",
            params={"clientId": client_id},
            headers=_api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("Failed to list projects for client %s: %s", client_id, exc)
        return []


# ── File downloading ──────────────────────────────────────────────────────────

def _classify_file(filename: str, mime: str = "") -> str:
    """Classify a file as 'logo', 'photo', or 'document'."""
    name_lower = filename.lower()
    if "logo" in name_lower:
        return "logo"
    mime_type = mime or mimetypes.guess_type(filename)[0] or ""
    if mime_type.startswith("image/"):
        return "photo"
    return "document"


def _download_file(
    session: requests.Session,
    file_url: str,
    dest_path: Path,
) -> bool:
    """Download a single file. Returns True on success."""
    full_url = file_url if file_url.startswith("http") else urljoin(_PORTAL_BASE, file_url)
    try:
        resp = session.get(full_url, timeout=30, stream=True)
        resp.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        log.debug("Downloaded: %s → %s", file_url, dest_path)
        return True
    except Exception as exc:
        log.warning("Failed to download %s: %s", file_url, exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def sync_client_assets(
    lead: dict,
    force: bool = False,
) -> dict:
    """
    Download all client-uploaded assets from the portal for a given lead.

    Args:
        lead:  CRM lead dict (must have 'id' and 'email')
        force: Re-download even if assets already exist locally

    Returns:
        manifest = {
            "lead_id": int,
            "client_id": str | None,
            "asset_dir": str,
            "logo": str | None,       # relative path to logo file
            "photos": [str],          # relative paths to photo files
            "documents": [str],       # relative paths to document files
            "total_files": int,
            "ready": bool,            # True if minimum assets are present
            "missing": [str],         # list of missing required items
        }
    """
    lead_id = lead["id"]
    email = lead.get("email")
    asset_dir = _CLIENTS_DIR / str(lead_id) / "assets"

    manifest: dict = {
        "lead_id": lead_id,
        "client_id": None,
        "asset_dir": str(asset_dir),
        "logo": None,
        "photos": [],
        "documents": [],
        "total_files": 0,
        "ready": False,
        "missing": [],
    }

    # Check if already synced (unless force=True)
    if not force and asset_dir.exists() and any(asset_dir.rglob("*.*")):
        existing = list(asset_dir.rglob("*.*"))
        log.info("Assets already synced for lead #%d (%d files). Use force=True to re-sync.", lead_id, len(existing))
        return _scan_existing_assets(manifest, asset_dir)

    if not email:
        log.warning("Lead #%d has no email — cannot look up portal client", lead_id)
        manifest["missing"].append("email (required to find portal client)")
        return manifest

    session = _get_session()
    if session is None:
        log.warning(
            "Portal login failed — asset sync skipped for lead #%d.\n"
            "Set CURBSITE_OWNER_EMAIL and CURBSITE_OWNER_PASSWORD in .env.",
            lead_id,
        )
        manifest["missing"].append("portal_credentials")
        return manifest

    # Find portal client ID by email
    client_id = _find_client_id(session, email)
    if not client_id:
        manifest["missing"].append(f"portal_account (no client found for {email})")
        log.info(
            "Client %s hasn't created a portal account yet. "
            "Send them the portal registration link: %s/portal/register",
            email, _PORTAL_BASE,
        )
        return manifest

    manifest["client_id"] = client_id

    # Get projects
    projects = _list_projects(session, client_id)
    if not projects:
        manifest["missing"].append("projects (no projects found in portal)")
        return manifest

    # Download all files from all projects
    asset_dir.mkdir(parents=True, exist_ok=True)
    photos_dir = asset_dir / "photos"
    docs_dir = asset_dir / "documents"
    photos_dir.mkdir(exist_ok=True)
    docs_dir.mkdir(exist_ok=True)

    downloaded = 0
    for project in projects:
        files = project.get("files", [])
        for f in files:
            file_url = f.get("url", "")
            original_name = f.get("name", "file")
            mime = f.get("type", "")

            category = _classify_file(original_name, mime)

            if category == "logo":
                dest = asset_dir / original_name
            elif category == "photo":
                dest = photos_dir / original_name
            else:
                dest = docs_dir / original_name

            # Avoid overwriting with same name — prepend project ID
            if dest.exists() and not force:
                stem = dest.stem
                dest = dest.with_stem(f"{project.get('id','')[:8]}_{stem}")

            if _download_file(session, file_url, dest):
                downloaded += 1
                rel = str(dest.relative_to(asset_dir))
                if category == "logo" and not manifest["logo"]:
                    manifest["logo"] = rel
                elif category == "photo":
                    manifest["photos"].append(rel)
                else:
                    manifest["documents"].append(rel)

    manifest["total_files"] = downloaded
    log.info(
        "Portal sync complete for lead #%d: %d files downloaded (logo=%s, photos=%d, docs=%d)",
        lead_id, downloaded,
        "yes" if manifest["logo"] else "no",
        len(manifest["photos"]),
        len(manifest["documents"]),
    )

    return _validate_manifest(manifest)


def _scan_existing_assets(manifest: dict, asset_dir: Path) -> dict:
    """Populate manifest from an already-synced asset directory."""
    for f in asset_dir.iterdir():
        if f.is_file():
            cat = _classify_file(f.name)
            rel = str(f.relative_to(asset_dir))
            if cat == "logo" and not manifest["logo"]:
                manifest["logo"] = rel

    photos_dir = asset_dir / "photos"
    if photos_dir.exists():
        manifest["photos"] = [str(f.relative_to(asset_dir)) for f in photos_dir.iterdir() if f.is_file()]

    docs_dir = asset_dir / "documents"
    if docs_dir.exists():
        manifest["documents"] = [str(f.relative_to(asset_dir)) for f in docs_dir.iterdir() if f.is_file()]

    manifest["total_files"] = len(manifest["photos"]) + len(manifest["documents"]) + (1 if manifest["logo"] else 0)
    return _validate_manifest(manifest)


def _validate_manifest(manifest: dict) -> dict:
    """Check if minimum build requirements are met."""
    missing = list(manifest.get("missing", []))

    if not manifest.get("logo"):
        missing.append("logo (will use text wordmark fallback)")

    if len(manifest.get("photos", [])) < 3:
        missing.append(f"photos (have {len(manifest.get('photos',[]))}, need at least 3)")

    # Ready if we have at least photos (logo is optional)
    manifest["ready"] = len(manifest.get("photos", [])) >= 1
    manifest["missing"] = missing
    return manifest


def assert_assets_ready(lead: dict, min_photos: int = 3) -> bool:
    """
    Sync assets and return True only if the minimum build requirements are met.
    Blocks the build pipeline if assets aren't ready.
    """
    manifest = sync_client_assets(lead)
    photos_count = len(manifest.get("photos", []))

    if not manifest["ready"] or photos_count < min_photos:
        log.warning(
            "Lead #%d (%s) assets NOT ready:\n  %s\n"
            "  Action: Ask client to upload files at %s/portal and re-run.",
            lead["id"],
            lead.get("business_name"),
            "\n  ".join(manifest.get("missing", ["unknown"])),
            _PORTAL_BASE,
        )
        return False

    log.info(
        "Lead #%d assets ready: logo=%s, photos=%d, docs=%d",
        lead["id"],
        "yes" if manifest.get("logo") else "no (text fallback)",
        photos_count,
        len(manifest.get("documents", [])),
    )
    return True


# ── Account creation & status/invoice sync ────────────────────────────────────

_PORTAL_STATUS_MAP: dict[str, str] = {
    "building":    "In Progress",
    "build_ready": "Awaiting Approval",
    "deployed":    "Final Review",
    "live":        "Complete",
}

TIER_TO_PACKAGE: dict[str, str] = {
    "entry": "Entry",
    "mid":   "Mid",
    "top":   "Top",
}


def _save_portal_ids(lead_id: int, client_id: str = "", project_id: str = "") -> None:
    """Write portal IDs into the leads table."""
    from src.crm.database import get_conn
    now = datetime.utcnow().isoformat()
    updates: list[str] = []
    vals: list = []
    if client_id:
        updates.append("portal_client_id=?")
        vals.append(client_id)
    if project_id:
        updates.append("portal_project_id=?")
        vals.append(project_id)
    if not updates:
        return
    updates.append("updated_at=?")
    vals.extend([now, lead_id])
    with get_conn() as conn:
        conn.execute(f"UPDATE leads SET {', '.join(updates)} WHERE id=?", vals)


def create_portal_account(lead: dict) -> Optional[str]:
    """
    Create a new client account and project in the curbsite.co portal.

    Returns:
      - The temporary password string when a new account is created.
      - "__existing__" when the account already exists (idempotent).
      - None on failure.

    Steps:
      1. POST /api/clients/register  (public, no auth) → get portal client id
      2. POST /api/projects          (admin session)   → get portal project id
    Both IDs are persisted to the leads table (portal_client_id, portal_project_id).
    """
    email = lead.get("email")
    if not email:
        return None

    temp_password = secrets.token_urlsafe(10)

    # Admin session needed for project creation; also used to check existing accounts.
    session = _get_session()
    if session is None:
        log.warning("create_portal_account: portal login failed for %s", email)
        return None

    # ── Step 1: Register client (public endpoint — no auth) ───────────────────
    portal_client_id = lead.get("portal_client_id") or _find_client_id(session, email)
    result: Optional[str]

    if portal_client_id:
        log.info(
            "Portal client already exists for %s (id=%s) — skipping registration",
            email, portal_client_id,
        )
        result = "__existing__"
    else:
        try:
            reg_resp = requests.post(
                f"{_PORTAL_BASE}/api/clients/register",
                json={
                    "name":         lead.get("owner_name") or lead.get("business_name", ""),
                    "email":        email,
                    "password":     temp_password,
                    "businessName": lead.get("business_name", ""),
                    "phone":        lead.get("phone", ""),
                },
                headers={"Content-Type": "application/json", "User-Agent": "CurbsiteAgent/1.0"},
                timeout=15,
            )
            if reg_resp.status_code not in (200, 201):
                log.error(
                    "Portal client registration failed for %s: HTTP %d — %s",
                    email, reg_resp.status_code, reg_resp.text[:300],
                )
                return None
            data = reg_resp.json()
            portal_client_id = (
                data.get("id")
                or (data.get("client") or {}).get("id")
            )
            if not portal_client_id:
                log.error("Portal registration response missing client id: %s", data)
                return None
            log.info("Portal client registered for %s (id=%s, lead #%d)", email, portal_client_id, lead.get("id", 0))
            result = temp_password
        except Exception as exc:
            log.error("Portal client registration request failed: %s", exc)
            return None

    _save_portal_ids(lead["id"], client_id=portal_client_id)

    # ── Step 2: Create project (admin session) ────────────────────────────────
    if lead.get("portal_project_id"):
        log.debug("Portal project already exists for lead #%d — skipping", lead.get("id", 0))
        return result

    package = TIER_TO_PACKAGE.get((lead.get("tier") or "entry").lower(), "Entry")
    biz_name = lead.get("business_name", "Website")
    try:
        proj_resp = session.post(
            f"{_PORTAL_BASE}/api/projects",
            json={
                "clientId":    portal_client_id,
                "name":        f"{biz_name} Website",
                "description": f"Website project for {biz_name}",
                "package":     package,
                "status":      "Discovery",
            },
            headers=_api_headers(),
            timeout=15,
        )
        if proj_resp.status_code not in (200, 201):
            log.error(
                "Portal project creation failed for lead #%d: HTTP %d — %s",
                lead.get("id", 0), proj_resp.status_code, proj_resp.text[:300],
            )
            return result  # client was created; project failed but not fatal
        proj_data = proj_resp.json()
        portal_project_id = (
            proj_data.get("id")
            or (proj_data.get("project") or {}).get("id")
        )
        if portal_project_id:
            _save_portal_ids(lead["id"], project_id=portal_project_id)
            log.info(
                "Portal project created for lead #%d (project_id=%s, package=%s)",
                lead.get("id", 0), portal_project_id, package,
            )
        else:
            log.warning("Portal project creation response missing id: %s", proj_data)
    except Exception as exc:
        log.error("Portal project creation request failed: %s", exc)

    return result


def sync_lead_status_to_portal(lead: dict) -> bool:
    """
    Push the current pipeline status to the client's portal project.

    Uses lead.portal_project_id directly when available; falls back to
    email → client lookup → first project scan. Only syncs statuses in
    _PORTAL_STATUS_MAP; silently skips others. Returns True on success.
    """
    status = lead.get("status", "")
    portal_label = _PORTAL_STATUS_MAP.get(status)
    if not portal_label:
        log.debug(
            "sync_lead_status_to_portal: no portal label for status '%s' — skipping", status
        )
        return False

    session = _get_session()
    if session is None:
        log.warning("sync_lead_status_to_portal: portal login failed — status sync skipped")
        return False

    portal_project_id = lead.get("portal_project_id")
    if not portal_project_id:
        # Fall back to lookup via email
        email = lead.get("email")
        if not email:
            return False
        client_id = lead.get("portal_client_id") or _find_client_id(session, email)
        if not client_id:
            log.warning(
                "sync_lead_status_to_portal: client %s not found in portal — "
                "call create_portal_account first",
                email,
            )
            return False
        projects = _list_projects(session, client_id)
        if not projects:
            log.warning(
                "sync_lead_status_to_portal: no portal project for client %s", client_id
            )
            return False
        portal_project_id = projects[0].get("id")
        if not portal_project_id:
            return False

    try:
        resp = session.patch(
            f"{_PORTAL_BASE}/api/projects/{portal_project_id}",
            json={"status": portal_label},
            headers=_api_headers(),
            timeout=15,
        )
        if resp.status_code in (200, 201, 204):
            log.info(
                "Portal status updated for lead #%d: '%s' → '%s'",
                lead.get("id", 0), status, portal_label,
            )
            return True
        log.error(
            "Portal status sync failed for lead #%d: HTTP %d — %s",
            lead.get("id", 0), resp.status_code, resp.text[:200],
        )
        return False
    except Exception as exc:
        log.error("Portal status sync request failed: %s", exc)
        return False


def sync_invoice_to_portal(
    lead: dict,
    payment_amount: float,
    processor: str,
    transaction_id: str,
    is_final: bool,
) -> bool:
    """
    Mark the matching portal invoice as Paid via PATCH /api/invoices/{id}.

    Coordination note: When clients pay through the portal's own Square checkout,
    the portal's /api/square/webhook automatically marks the invoice Paid — this
    function handles Stripe payments and any Square payments initiated outside the
    portal. The sales agent's /webhook/square focuses only on pipeline state
    transitions (deposit → build, final → go-live); the portal invoice side is
    handled automatically by the portal's own Square webhook.

    Args:
        lead:           CRM lead dict (portal_client_id preferred; email as fallback)
        payment_amount: Amount paid in USD
        processor:      'stripe' | 'square'
        transaction_id: Payment reference ID from the processor
        is_final:       True = final payment, False = deposit
    """
    portal_client_id = lead.get("portal_client_id")
    email = lead.get("email")

    if not portal_client_id and not email:
        return False

    session = _get_session()
    if session is None:
        log.warning("sync_invoice_to_portal: portal login failed — invoice sync skipped")
        return False

    if not portal_client_id:
        portal_client_id = _find_client_id(session, email)
        if not portal_client_id:
            log.warning(
                "sync_invoice_to_portal: client %s not in portal — invoice sync skipped", email
            )
            return False

    # Fetch projects with embedded invoices to find the matching one
    projects = _list_projects(session, portal_client_id)
    if not projects:
        log.warning(
            "sync_invoice_to_portal: no projects found for client %s", portal_client_id
        )
        return False

    invoice_id: Optional[str] = None
    for project in projects:
        for inv in project.get("invoices", []):
            if (inv.get("status") or "").lower() == "paid":
                continue
            # Prefer match by payment session ID stored on the invoice
            if inv.get("stripeSessionId") == transaction_id:
                invoice_id = inv.get("id")
                break
            # Fall back: match by invoice type (portal auto-creates deposit + final)
            inv_type = (inv.get("type") or "").lower()
            if is_final and inv_type == "final":
                invoice_id = inv.get("id")
                break
            if not is_final and inv_type == "deposit":
                invoice_id = inv.get("id")
                break
        if invoice_id:
            break

    if not invoice_id:
        log.warning(
            "sync_invoice_to_portal: no unpaid %s invoice found for lead #%d (client %s)",
            "final" if is_final else "deposit",
            lead.get("id", 0),
            portal_client_id,
        )
        return False

    try:
        resp = session.patch(
            f"{_PORTAL_BASE}/api/invoices/{invoice_id}",
            json={"status": "Paid"},
            headers=_api_headers(),
            timeout=15,
        )
        if resp.status_code in (200, 201, 204):
            log.info(
                "Invoice %s marked Paid for lead #%d: $%.2f via %s (final=%s)",
                invoice_id, lead.get("id", 0), payment_amount, processor, is_final,
            )
            return True
        log.error(
            "Portal invoice sync failed for lead #%d (inv %s): HTTP %d — %s",
            lead.get("id", 0), invoice_id, resp.status_code, resp.text[:200],
        )
        return False
    except Exception as exc:
        log.error("Portal invoice sync request failed: %s", exc)
        return False
