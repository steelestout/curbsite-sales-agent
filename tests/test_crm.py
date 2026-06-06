"""Tests for the CRM database layer."""

import os
import pytest
import tempfile
from pathlib import Path

# Patch DB_PATH before imports
_tmp = tempfile.mktemp(suffix=".db")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")

from src.crm.database import (
    init_db,
    upsert_lead,
    get_lead,
    get_leads,
    update_lead_status,
    log_outreach,
    enqueue_followup,
    get_due_followups,
    mark_followup_sent,
    log_cost,
    get_conn,
)
from src.config import DB_PATH


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets a fresh in-memory DB."""
    db = tmp_path / "test.db"
    monkeypatch.setattr("src.crm.database.DB_PATH", db)
    monkeypatch.setattr("src.config.DB_PATH", db)
    init_db(db)
    yield db


def _sample_lead(**overrides):
    base = {
        "business_name": "Joe's Pizza",
        "city": "Kokomo",
        "state": "IN",
        "niche": "restaurant",
        "email": "joe@joespizza.com",
        "phone": "7654321000",
        "website_quality": "none",
        "has_website": 0,
        "score": 55,
        "status": "new",
        "source": "yelp",
    }
    base.update(overrides)
    return base


def test_upsert_creates_lead(fresh_db):
    lead_id = upsert_lead(_sample_lead())
    assert lead_id > 0


def test_upsert_deduplicates(fresh_db):
    id1 = upsert_lead(_sample_lead())
    id2 = upsert_lead(_sample_lead(score=70))  # same name+city
    assert id1 == id2  # same row updated


def test_get_lead(fresh_db):
    lead_id = upsert_lead(_sample_lead())
    lead = get_lead(lead_id)
    assert lead["business_name"] == "Joe's Pizza"
    assert lead["city"] == "Kokomo"


def test_get_leads_filter_status(fresh_db):
    upsert_lead(_sample_lead(status="new"))
    upsert_lead(_sample_lead(business_name="Marco's", status="scored"))
    new = get_leads(status="new")
    assert len(new) == 1
    assert new[0]["business_name"] == "Joe's Pizza"


def test_get_leads_min_score(fresh_db):
    upsert_lead(_sample_lead(score=30))
    upsert_lead(_sample_lead(business_name="High Score", score=80))
    high = get_leads(min_score=50)
    assert len(high) == 1
    assert high[0]["business_name"] == "High Score"


def test_update_lead_status(fresh_db):
    lead_id = upsert_lead(_sample_lead())
    update_lead_status(lead_id, "emailed", notes="sent welcome")
    lead = get_lead(lead_id)
    assert lead["status"] == "emailed"
    assert "sent welcome" in lead["notes"]


def test_log_outreach(fresh_db):
    lead_id = upsert_lead(_sample_lead())
    log_id = log_outreach(lead_id, "email", subject="Hello", body="Hi there")
    assert log_id > 0


def test_followup_queue(fresh_db):
    lead_id = upsert_lead(_sample_lead(status="emailed", email="joe@joespizza.com"))
    enqueue_followup(lead_id, step=1, scheduled_for="2000-01-01T09:00:00")
    due = get_due_followups()
    assert len(due) == 1
    assert due[0]["lead_id"] == lead_id
    mark_followup_sent(due[0]["id"])
    assert get_due_followups() == []


def test_log_cost(fresh_db):
    log_cost("score_lead", "gpt-4o-mini", 100, 50)
    log_cost("draft_email", "gpt-4o-mini", 200, 150, cached=True)

    with get_conn(fresh_db) as conn:
        rows = conn.execute("SELECT * FROM cost_log").fetchall()
    assert len(rows) == 2
    # Verify cost calculation for gpt-4o-mini
    # 100 * 0.15/1M + 50 * 0.60/1M = 0.000015 + 0.000030 = 0.000045
    assert abs(rows[0]["cost_usd"] - 0.000045) < 1e-8
    assert rows[1]["cached"] == 1
