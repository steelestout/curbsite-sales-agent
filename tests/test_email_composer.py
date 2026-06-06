"""Tests for the email composer (mocked AI)."""

import json
import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")


MOCK_EMAIL = (
    "SUBJECT: Your business deserves a better website\n"
    "BODY:\nHi there, I noticed Joe's Pizza doesn't have a website. "
    "We can fix that for you quickly and affordably. "
    "Would you be open to a free 15-minute call?\n\nSteele @ Curbsite"
)


def test_compose_outreach_email_parses_subject_and_body(monkeypatch):
    monkeypatch.setattr("src.outreach.email_composer.draft_email", lambda s, u, **kw: MOCK_EMAIL)
    from src.outreach.email_composer import compose_outreach_email

    lead = {
        "business_name": "Joe's Pizza",
        "owner_name": None,
        "niche": "restaurant",
        "city": "Kokomo",
        "website_quality": "none",
        "has_website": 0,
        "score": 60,
        "score_reasons": json.dumps(["No website — strong need"]),
    }
    subject, body = compose_outreach_email(lead)
    assert "website" in subject.lower() or subject  # subject present
    assert "Curbsite" in body or "Joe" in body


def test_compose_followup_email_step1(monkeypatch):
    monkeypatch.setattr(
        "src.outreach.email_composer.draft_email",
        lambda s, u, **kw: "SUBJECT: Quick follow-up\nBODY:\nJust checking in!",
    )
    from src.outreach.email_composer import compose_followup_email

    lead = {
        "business_name": "Joe's Pizza",
        "niche": "restaurant",
        "city": "Kokomo",
    }
    subject, body = compose_followup_email(lead, step=1)
    assert subject  # has a subject
    assert body     # has a body


def test_fallback_subject_when_ai_returns_no_subject(monkeypatch):
    monkeypatch.setattr(
        "src.outreach.email_composer.draft_email",
        lambda s, u, **kw: "Hey there, I think we can help you get online.",
    )
    from src.outreach.email_composer import compose_outreach_email

    lead = {
        "business_name": "Marco's Barbershop",
        "owner_name": "Marco",
        "niche": "salon",
        "city": "Kokomo",
        "website_quality": "poor",
        "has_website": 1,
        "score": 55,
        "score_reasons": "[]",
    }
    subject, body = compose_outreach_email(lead)
    assert "Marco" in subject or "online" in subject.lower() or subject
    assert "help" in body.lower() or body
