"""
SQLite-based CRM — single source of truth for all leads.

Tables
──────
leads            — one row per business
outreach_log     — every email / call attempt
followup_queue   — scheduled follow-ups
cost_log         — per-operation AI cost tracking
mockups          — generated mockup files
builds           — production site builds
domains          — registered domains
vps_instances    — client VPS servers (Track A)
approval_tokens  — Steele approve/reject tokens for built sites
pagespeed_cache  — Google PageSpeed API response cache (7-day TTL)
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import DB_PATH

log = logging.getLogger(__name__)


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name   TEXT NOT NULL,
    owner_name      TEXT,
    email           TEXT,
    phone           TEXT,
    website         TEXT,
    niche           TEXT,
    city            TEXT,
    state           TEXT,
    address         TEXT,
    hours           TEXT,
    score           INTEGER DEFAULT 0,
    score_reasons   TEXT,          -- JSON list of reason strings
    has_website     INTEGER DEFAULT 0,
    website_quality TEXT,          -- 'none' | 'poor' | 'okay' | 'good'
    google_rating   REAL,
    review_count    INTEGER,
    social_links    TEXT,          -- JSON
    status          TEXT DEFAULT 'new',
    -- new | scored | mockup_ready | emailed | followed_up | mockup_sent | agreed_pending
    -- agreed | building | build_ready | domain_purchased | vps_provisioned | deployed | live
    -- delivered (Track B) | lost | unsubscribed
    tier            TEXT,          -- 'entry' | 'mid' | 'top'
    care_plan       REAL,          -- monthly care plan price; NULL = no care plan (→ Track B)
    domain          TEXT,          -- registered domain name once purchased
    source          TEXT,          -- 'yelp_scrape' | 'google_maps' | 'manual'
    review_needed   INTEGER DEFAULT 0,  -- 1 = flag for Steele to review
    has_engagement  INTEGER DEFAULT 0,  -- 1 = prior email open/click (FCC gate for Rook)
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outreach_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL REFERENCES leads(id),
    type        TEXT NOT NULL,     -- 'email' | 'call'
    subject     TEXT,
    body        TEXT,
    sent_at     TEXT DEFAULT (datetime('now')),
    opened      INTEGER DEFAULT 0,
    replied     INTEGER DEFAULT 0,
    bounced     INTEGER DEFAULT 0,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS followup_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         INTEGER NOT NULL REFERENCES leads(id),
    sequence_step   INTEGER DEFAULT 1,
    scheduled_for   TEXT NOT NULL,
    sent            INTEGER DEFAULT 0,
    sent_at         TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cost_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    operation   TEXT NOT NULL,     -- 'score_lead' | 'draft_email' | 'followup'
    model       TEXT,
    input_tok   INTEGER DEFAULT 0,
    output_tok  INTEGER DEFAULT 0,
    cost_usd    REAL DEFAULT 0.0,
    cached      INTEGER DEFAULT 0, -- 1 if served from disk cache
    logged_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mockups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id      INTEGER UNIQUE NOT NULL REFERENCES leads(id),
    html_path    TEXT,
    netlify_url  TEXT,    -- public URL of the deployed mockup (used as email hook)
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS builds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER UNIQUE NOT NULL REFERENCES leads(id),
    site_path   TEXT,
    status      TEXT DEFAULT 'pending',  -- 'pending' | 'building' | 'ready' | 'deployed'
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS domains (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id        INTEGER UNIQUE NOT NULL REFERENCES leads(id),
    domain_name    TEXT NOT NULL,
    registrar      TEXT DEFAULT 'namecheap',
    purchase_date  TEXT,
    expiry_date    TEXT
);

CREATE TABLE IF NOT EXISTS vps_instances (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id             INTEGER UNIQUE NOT NULL REFERENCES leads(id),
    hetzner_server_id   INTEGER,       -- Hetzner Cloud server ID for deprovisioning
    ip                  TEXT,          -- public IPv4 address
    server_type         TEXT,          -- 'standard' | 'performance'
    domain              TEXT,          -- client domain hosted on this VPS
    monthly_cost        REAL,          -- USD/mo (~5 or ~9)
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approval_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL REFERENCES leads(id),
    token       TEXT NOT NULL UNIQUE,
    action      TEXT NOT NULL,    -- 'approve' | 'reject'
    used        INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pagespeed_cache (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,
    mobile_score  INTEGER,
    desktop_score INTEGER,
    cached_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT NOT NULL UNIQUE,
    smtp_host    TEXT NOT NULL,
    smtp_port    INTEGER DEFAULT 587,
    from_name    TEXT,
    warmup_day   INTEGER DEFAULT 1,
    active       INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id       INTEGER NOT NULL REFERENCES leads(id),
    to_email      TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    html_body     TEXT DEFAULT '',
    status        TEXT DEFAULT 'pending',  -- 'pending' | 'sent' | 'failed'
    queued_at     TEXT DEFAULT (datetime('now')),
    scheduled_for TEXT NOT NULL,
    sent_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_status      ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_score       ON leads(score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_email       ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_review      ON leads(review_needed);
CREATE INDEX IF NOT EXISTS idx_followup_sched    ON followup_queue(scheduled_for, sent);
CREATE INDEX IF NOT EXISTS idx_approval_token    ON approval_tokens(token);
CREATE INDEX IF NOT EXISTS idx_pagespeed_url     ON pagespeed_cache(url);
"""

# Indexes that depend on columns added via migration (can't be in SCHEMA executescript).
_POST_MIGRATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_leads_golive ON leads(golive_at)",
]


# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def get_conn(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# New columns added to the leads table after initial schema was created.
# SQLite doesn't support IF NOT EXISTS on ALTER TABLE — we catch the OperationalError.
_OUTREACH_MIGRATIONS: list[tuple[str, str]] = [
    ("sender_email", "TEXT"),   # which account sent this message
]


def _migrate_outreach_log(conn: sqlite3.Connection) -> None:
    for col, col_def in _OUTREACH_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE outreach_log ADD COLUMN {col} {col_def}")
        except sqlite3.OperationalError:
            pass  # column already exists


_LEAD_MIGRATIONS: list[tuple[str, str]] = [
    ("pagespeed_mobile",     "INTEGER"),
    ("pagespeed_cached_at",  "TEXT"),
    ("golive_at",            "TEXT"),
    ("review_requested_at",  "TEXT"),
    ("review_reminder_sent", "TEXT"),
    ("review_received",      "INTEGER DEFAULT 0"),
    ("referral_link",        "TEXT"),
    ("referrals_sent",       "INTEGER DEFAULT 0"),
    ("referrals_converted",  "INTEGER DEFAULT 0"),
    ("build_approved",       "INTEGER DEFAULT 0"),
    ("revision_needed",      "INTEGER DEFAULT 0"),
    ("stripe_deposit_id",    "TEXT"),
    ("stripe_final_id",      "TEXT"),
    ("stripe_payment_url",   "TEXT"),
    ("payment_processor",    "TEXT DEFAULT 'stripe'"),
    ("square_payment_id",    "TEXT"),
    ("portal_client_id",     "TEXT"),
    ("portal_project_id",    "TEXT"),
    # Postcard outreach (Lob.com)
    ("address_line1",        "TEXT"),
    ("zip_code",             "TEXT"),
    ("postcard_id",          "TEXT"),
    ("postcard_sent_at",     "TEXT"),
]


def _migrate_leads(conn: sqlite3.Connection) -> None:
    for col, col_def in _LEAD_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_def}")
        except sqlite3.OperationalError:
            pass  # column already exists


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables, run column migrations, then create post-migration indexes."""
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate_leads(conn)
        _migrate_outreach_log(conn)
        for sql in _POST_MIGRATION_INDEXES:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
    log.info("Database ready: %s", db_path)


# ── Lead CRUD ─────────────────────────────────────────────────────────────────

def upsert_lead(data: dict) -> int:
    """
    Insert or update a lead by (business_name, city).
    Returns the lead id.
    """
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM leads WHERE business_name=? AND city=?",
            (data.get("business_name"), data.get("city")),
        ).fetchone()

        if existing:
            lead_id = existing["id"]
            updates = {k: v for k, v in data.items() if k not in ("id", "created_at")}
            updates["updated_at"] = now
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE leads SET {set_clause} WHERE id=?",
                [*updates.values(), lead_id],
            )
            log.debug("Updated lead #%d: %s", lead_id, data.get("business_name"))
        else:
            data.setdefault("created_at", now)
            data["updated_at"] = now
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" for _ in data)
            cur = conn.execute(
                f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
                list(data.values()),
            )
            lead_id = cur.lastrowid
            log.debug("Inserted lead #%d: %s", lead_id, data.get("business_name"))
    return lead_id


def get_lead(lead_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    return dict(row) if row else None


def get_leads(
    status: Optional[str] = None,
    min_score: int = 0,
    limit: int = 100,
) -> list[dict]:
    query = "SELECT * FROM leads WHERE score >= ?"
    params: list = [min_score]
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY score DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_lead_status(lead_id: int, status: str, notes: str = "") -> None:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status=?, notes=?, updated_at=? WHERE id=?",
            (status, notes, now, lead_id),
        )


def email_already_contacted(email: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM leads WHERE email=? AND status NOT IN ('new','scored')",
            (email,),
        ).fetchone()
    return row is not None


# ── Outreach log ──────────────────────────────────────────────────────────────

def log_outreach(
    lead_id: int,
    type_: str,
    subject: str = "",
    body: str = "",
    error: str = "",
    sender_email: str = "",
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO outreach_log (lead_id, type, subject, body, error, sender_email)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lead_id, type_, subject, body, error, sender_email or None),
        )
    return cur.lastrowid


# ── Follow-up queue ───────────────────────────────────────────────────────────

def enqueue_followup(lead_id: int, step: int, scheduled_for: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO followup_queue
               (lead_id, sequence_step, scheduled_for)
               VALUES (?, ?, ?)""",
            (lead_id, step, scheduled_for),
        )


def get_due_followups() -> list[dict]:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT fq.*, l.business_name, l.email, l.owner_name, l.niche, l.city
               FROM followup_queue fq
               JOIN leads l ON l.id = fq.lead_id
               WHERE fq.sent=0 AND fq.scheduled_for <= ?
               ORDER BY fq.scheduled_for""",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_followup_sent(followup_id: int) -> None:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE followup_queue SET sent=1, sent_at=? WHERE id=?",
            (now, followup_id),
        )


# ── Cost tracking ─────────────────────────────────────────────────────────────

def log_cost(
    operation: str,
    model: str,
    input_tok: int,
    output_tok: int,
    cached: bool = False,
) -> None:
    # GPT-4o-mini: $0.15/1M in, $0.60/1M out
    # GPT-4o:      $5.00/1M in, $15.00/1M out
    rates = {
        "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
        "gpt-4o":      (5.00 / 1_000_000, 15.00 / 1_000_000),
    }
    in_rate, out_rate = rates.get(model, (0.0, 0.0))
    cost = (input_tok * in_rate) + (output_tok * out_rate)

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO cost_log (operation, model, input_tok, output_tok, cost_usd, cached)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (operation, model, input_tok, output_tok, cost, int(cached)),
        )
