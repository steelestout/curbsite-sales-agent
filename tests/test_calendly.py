"""Tests for Calendly link generation."""

import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")


def test_booking_link_with_calendly_url(monkeypatch):
    monkeypatch.setattr(
        "src.outreach.calendly.CALENDLY_URL",
        "https://calendly.com/steele-curbsite/15min",
    )
    from src.outreach.calendly import booking_link
    lead = {"id": 42, "business_name": "Joe's Pizza", "owner_name": "Joe"}
    link = booking_link(lead, campaign="cold_email")
    assert "calendly.com" in link
    assert "utm_source=curbsite_agent" in link
    assert "utm_medium=cold_email" in link
    assert "42" in link  # lead id in utm_content


def test_booking_link_without_calendly_url(monkeypatch):
    monkeypatch.setattr("src.outreach.calendly.CALENDLY_URL", "")
    from src.outreach.calendly import booking_link
    lead = {"id": 1, "business_name": "Biz"}
    link = booking_link(lead)
    assert "YOUR_LINK_HERE" in link


def test_booking_cta_includes_link(monkeypatch):
    monkeypatch.setattr(
        "src.outreach.calendly.CALENDLY_URL",
        "https://calendly.com/steele-curbsite/15min",
    )
    from src.outreach.calendly import booking_cta
    lead = {"id": 5, "business_name": "Marco's", "owner_name": "Marco"}
    cta = booking_cta(lead, campaign="cold_email")
    assert "calendly.com" in cta
    assert "15" in cta  # references free 15-min


def test_booking_cta_no_owner_name(monkeypatch):
    monkeypatch.setattr(
        "src.outreach.calendly.CALENDLY_URL",
        "https://calendly.com/steele-curbsite/15min",
    )
    from src.outreach.calendly import booking_cta
    lead = {"id": 5, "business_name": "Marco's"}
    cta = booking_cta(lead)
    assert "calendly.com" in cta


def test_booking_link_slugifies_business_name(monkeypatch):
    monkeypatch.setattr(
        "src.outreach.calendly.CALENDLY_URL",
        "https://calendly.com/steele-curbsite/15min",
    )
    from src.outreach.calendly import booking_link
    lead = {"id": 7, "business_name": "Big City Roofing & Gutters LLC"}
    link = booking_link(lead)
    # Slug should be lowercase, hyphenated, max 30 chars
    assert "big-city-roofing" in link
