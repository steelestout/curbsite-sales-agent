"""
Central config loaded from .env.
All modules import from here — never read os.environ directly.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root (two levels up from src/)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# ── OpenAI ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
MODEL_DEFAULT: str = "gpt-4o-mini"      # cheap, fast — used everywhere
MODEL_QUALITY: str = "gpt-4o"           # used only for final email drafts

# ── Email (SMTP) ─────────────────────────────────────────────────────────────
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.environ["SMTP_USER"]
SMTP_PASS: str = os.environ["SMTP_PASS"]
FROM_NAME: str = os.getenv("FROM_NAME", "Steele @ Curbsite")
FROM_EMAIL: str = os.getenv("FROM_EMAIL", SMTP_USER)
REPLY_TO: str = os.getenv("REPLY_TO", FROM_EMAIL)

# ── Agency identity ──────────────────────────────────────────────────────────
AGENCY_NAME: str = os.getenv("AGENCY_NAME", "Curbsite.co")
AGENCY_URL: str = os.getenv("AGENCY_URL", "https://curbsite.co")
AGENCY_OWNER: str = os.getenv("AGENCY_OWNER", "Steele Stout")

# ── Targeting ────────────────────────────────────────────────────────────────
TARGET_CITIES: list[str] = [
    c.strip() for c in os.getenv("TARGET_CITIES", "Kokomo").split(",") if c.strip()
]
TARGET_NICHES: list[str] = [
    n.strip()
    for n in os.getenv(
        "TARGET_NICHES", "restaurant,photography,salon,contractor,fitness,dental"
    ).split(",")
    if n.strip()
]

# ── Calendly ─────────────────────────────────────────────────────────────────
CALENDLY_URL: str = os.getenv("CALENDLY_URL", "")
CALENDLY_WEBHOOK_SECRET: str = os.getenv("CALENDLY_WEBHOOK_SECRET", "")

# ── Scoring ───────────────────────────────────────────────────────────────────
SCORE_MIN_EMAIL: int = int(os.getenv("SCORE_MIN_EMAIL", "40"))

# ── Voice calling — intentionally disabled ────────────────────────────────────
# See src/outreach/openclaw.py for the full rationale (FCC compliance + trust).
VOICE_ENABLED: bool = False

# ── Rate limits ───────────────────────────────────────────────────────────────
MAX_EMAILS_PER_DAY: int = int(os.getenv("MAX_EMAILS_PER_DAY", "25"))
MAX_FOLLOWUPS_PER_WEEK: int = int(os.getenv("MAX_FOLLOWUPS_PER_WEEK", "50"))
PROSPECTING_DELAY: float = float(os.getenv("PROSPECTING_DELAY", "2"))
OUTREACH_DELAY: float = float(os.getenv("OUTREACH_DELAY", "5"))

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH: Path = _ROOT / os.getenv("DB_PATH", "data/leads/leads.db")
CACHE_DIR: Path = _ROOT / os.getenv("CACHE_DIR", "data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Mockup hosting (Netlify) ──────────────────────────────────────────────────
NETLIFY_ACCESS_TOKEN: str = os.getenv("NETLIFY_ACCESS_TOKEN", "")

# ── Domain registration (Namecheap) ──────────────────────────────────────────
NAMECHEAP_API_KEY: str = os.getenv("NAMECHEAP_API_KEY", "")
NAMECHEAP_USERNAME: str = os.getenv("NAMECHEAP_USERNAME", "")
NAMECHEAP_CLIENT_IP: str = os.getenv("NAMECHEAP_CLIENT_IP", "")
NAMECHEAP_SANDBOX: bool = os.getenv("NAMECHEAP_SANDBOX", "0") == "1"

# ── VPS deployment (Hostinger — shared infra for curbsite.co itself) ─────────
# NOTE: pk.ppk is PuTTY format. paramiko requires OpenSSH format.
# Convert: puttygen pk.ppk -O private-openssh -o ~/.ssh/curbsite_rsa
HOSTINGER_VPS_HOST: str = os.getenv("HOSTINGER_VPS_HOST", "187.77.5.53")
HOSTINGER_VPS_USER: str = os.getenv("HOSTINGER_VPS_USER", "root")
HOSTINGER_VPS_KEY_PATH: str = os.getenv(
    "HOSTINGER_VPS_KEY_PATH", str(Path.home() / ".ssh" / "curbsite_rsa")
)
HOSTINGER_VPS_IP: str = os.getenv("HOSTINGER_VPS_IP", "187.77.5.53")

# ── Client VPS provisioning (Hetzner — one VPS per client, Track A) ──────────
# Standard CX22 (~$5/mo): salons, contractors, auto, fitness
# Performance CX32 (~$9/mo): restaurants mid/top (online ordering load)
HETZNER_API_TOKEN: str = os.getenv("HETZNER_API_TOKEN", "")
HETZNER_DATACENTER: str = os.getenv("HETZNER_DATACENTER", "ash")   # Ashburn, VA
HETZNER_SSH_KEY_NAME: str = os.getenv("HETZNER_SSH_KEY_NAME", "curbsite")

# ── Reply monitoring (IMAP) ───────────────────────────────────────────────────
IMAP_HOST: str = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))

# ── Owner portal ──────────────────────────────────────────────────────────────
PORTAL_URL: str = os.getenv("CURBSITE_PORTAL_URL", "https://curbsite.co/portal")
PORTAL_FILE_BASE_PATH: str = os.getenv(
    "PORTAL_FILE_BASE_PATH", str(Path(__file__).resolve().parent.parent / "data" / "portal_uploads")
)

# ── OpenClaw / Rook voice agent ───────────────────────────────────────────────
OPENCLAW_API_KEY: str = os.getenv("OPENCLAW_API_KEY", "")
OPENCLAW_AGENT_ID: str = os.getenv("OPENCLAW_AGENT_ID", "")
OPENCLAW_API_BASE: str = os.getenv("OPENCLAW_API_BASE", "https://api.openclaw.ai/v1")

# ── Founding clients ──────────────────────────────────────────────────────────
# Number of free founding-client spots remaining (update as spots are filled)
FOUNDING_CLIENTS_REMAINING: int = int(os.getenv("FOUNDING_CLIENTS_REMAINING", "5"))

# ── Curbsite portal auth (for portal_sync.py) ─────────────────────────────────
CURBSITE_OWNER_EMAIL: str = os.getenv("CURBSITE_OWNER_EMAIL", "steele.stout@gmail.com")
CURBSITE_OWNER_PASSWORD: str = os.getenv("CURBSITE_OWNER_PASSWORD", "")
CURBSITE_CRM_API_KEY: str = os.getenv("CURBSITE_CRM_API_KEY", "")

# ── Stripe payments ───────────────────────────────────────────────────────────
STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_WEBHOOK_PORT: int = int(os.getenv("STRIPE_WEBHOOK_PORT", "5001"))

# ── Google PageSpeed Insights ─────────────────────────────────────────────────
GOOGLE_PAGESPEED_API_KEY: str = os.getenv("GOOGLE_PAGESPEED_API_KEY", "")

# ── Google Reviews ────────────────────────────────────────────────────────────
# Direct "Write a review" link for the Curbsite Google Business Profile
# Find it: Google Maps → your profile → "Get more reviews" → copy link
GOOGLE_REVIEW_URL: str = os.getenv("GOOGLE_REVIEW_URL", "")

# ── Owner dashboard ───────────────────────────────────────────────────────────
DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "http://localhost:5050")
DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "5050"))

# ── Steele's personal notification email ──────────────────────────────────────
STEELE_EMAIL: str = os.getenv("STEELE_EMAIL", "steele.stout@gmail.com")

# ── Voice scoring threshold (flags high-value leads for Rook outreach) ────────
SCORE_VOICE_THRESHOLD: int = int(os.getenv("SCORE_VOICE_THRESHOLD", "70"))

# ── Resend (transactional email) ──────────────────────────────────────────────
# Used for: client status emails, approvals, review requests, referrals, go-live
# Sign up: https://resend.com  |  Free: 3k emails/mo
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL: str = os.getenv("RESEND_FROM_EMAIL", f"{FROM_NAME} <{FROM_EMAIL}>")

# ── Instantly.ai (cold outreach) ──────────────────────────────────────────────
# Used for: initial cold emails and follow-up sequences to prospects
# Sign up: https://instantly.ai  |  ~$37/mo Hypergrowth
# INSTANTLY_CAMPAIGN_ID: add lead to a campaign (recommended for sequences)
# Leave blank to use direct-send mode (one-off API sends)
INSTANTLY_API_KEY: str = os.getenv("INSTANTLY_API_KEY", "")
INSTANTLY_CAMPAIGN_ID: str = os.getenv("INSTANTLY_CAMPAIGN_ID", "")
INSTANTLY_FROM_EMAIL: str = os.getenv("INSTANTLY_FROM_EMAIL", FROM_EMAIL)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
