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

# ── Scoring ──────────────────────────────────────────────────────────────────
SCORE_MIN_EMAIL: int = int(os.getenv("SCORE_MIN_EMAIL", "40"))
SCORE_VOICE_THRESHOLD: int = int(os.getenv("SCORE_VOICE_THRESHOLD", "85"))

# ── OpenClaw voice agent ─────────────────────────────────────────────────────
OPENCLAW_ENABLED: bool = os.getenv("OPENCLAW_ENABLED", "false").lower() == "true"
OPENCLAW_API_KEY: str = os.getenv("OPENCLAW_API_KEY", "")
OPENCLAW_AGENT_ID: str = os.getenv("OPENCLAW_AGENT_ID", "")

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

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
