"""Tests for the lead dossier generator."""

import json
import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")

from src.crm.database import init_db, upsert_lead


MOCK_AI_RESPONSE = (
    "OPENERS:\n"
    "- What made you get into the restaurant business?\n"
    "- How do most of your new customers find you right now?\n\n"
    "LIKELY OBJECTIONS:\n"
    "- 'I can't afford it' → Our Entry tier starts at $800 — less than most menu redesigns.\n"
    "- 'My nephew handles it' → Happy to take a look at what they've built, no pressure.\n"
    "- 'I already have Facebook' → Great — a site feeds Google, Facebook feeds regulars.\n\n"
    "CLOSING HOOK:\n"
    "If it sounds like a fit after our call, I'll send you a free mockup within 24 hours."
)


@pytest.fixture()
def db_with_lead(tmp_path, monkeypatch):
    """Fresh DB with one lead pre-inserted."""
    db = tmp_path / "test.db"
    monkeypatch.setattr("src.crm.database.DB_PATH", db)
    monkeypatch.setattr("src.config.DB_PATH", db)
    monkeypatch.setattr("src.crm.dossier.DOSSIERS_DIR", tmp_path / "dossiers")
    (tmp_path / "dossiers").mkdir()
    init_db(db)

    lead_id = upsert_lead({
        "business_name": "Joe's Pizza",
        "city": "Kokomo",
        "state": "IN",
        "niche": "restaurant",
        "email": "joe@joespizza.com",
        "phone": "7654321000",
        "website_quality": "none",
        "has_website": 0,
        "score": 68,
        "google_rating": 4.1,
        "review_count": 55,
        "status": "call_scheduled",
        "score_reasons": json.dumps([
            "No website — strong need",
            "Good review count (55) — has budget",
            "High-value niche: restaurant",
        ]),
        "source": "yelp",
    })
    return lead_id


def test_dossier_generates_markdown(db_with_lead, monkeypatch):
    monkeypatch.setattr(
        "src.crm.dossier._ai_conversation_prep",
        lambda lead, rec: MOCK_AI_RESPONSE,
    )
    monkeypatch.setattr(
        "src.outreach.calendly.CALENDLY_URL",
        "https://calendly.com/steele-curbsite/15min",
    )
    from src.crm.dossier import generate_dossier
    dossier = generate_dossier(db_with_lead, save=False)

    assert "Joe's Pizza" in dossier
    assert "Pre-Call Dossier" in dossier
    assert "68" in dossier           # score
    assert "restaurant" in dossier.lower()
    assert "Kokomo" in dossier
    assert "$" in dossier            # pricing mentioned
    assert "calendly.com" in dossier # booking link present
    assert "OPENERS" in dossier      # AI prep included


def test_dossier_contains_pricing_section(db_with_lead, monkeypatch):
    monkeypatch.setattr(
        "src.crm.dossier._ai_conversation_prep",
        lambda lead, rec: MOCK_AI_RESPONSE,
    )
    monkeypatch.setattr(
        "src.outreach.calendly.CALENDLY_URL",
        "https://calendly.com/steele-curbsite/15min",
    )
    from src.crm.dossier import generate_dossier
    dossier = generate_dossier(db_with_lead, save=False)

    # Should recommend Mid tier for a restaurant with 55 reviews
    assert "Mid Tier" in dossier or "Top Tier" in dossier
    assert "care plan" in dossier.lower()


def test_dossier_raises_for_missing_lead(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    monkeypatch.setattr("src.crm.database.DB_PATH", db)
    monkeypatch.setattr("src.config.DB_PATH", db)
    init_db(db)

    from src.crm.dossier import generate_dossier
    with pytest.raises(ValueError, match="not found"):
        generate_dossier(999, save=False)
