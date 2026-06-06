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
import shutil
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
