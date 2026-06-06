"""Tests for the lead scorer."""

import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")

from src.prospecting.scorer import _base_score, HIGH_VALUE_NICHES


def _lead(**kwargs):
    base = {
        "business_name": "Test Biz",
        "city": "Kokomo",
        "niche": "restaurant",
        "website_quality": "none",
        "has_website": 0,
        "google_rating": 4.0,
        "review_count": 75,
        "phone": "5551234567",
        "score_reasons": "[]",
    }
    base.update(kwargs)
    return base


def test_no_website_gives_high_base_score():
    score, reasons = _base_score(_lead(website_quality="none", has_website=0))
    assert score >= 50
    assert any("No website" in r for r in reasons)


def test_poor_website_scores_less_than_no_website():
    score_none, _ = _base_score(_lead(website_quality="none", has_website=0))
    score_poor, _ = _base_score(_lead(website_quality="poor", has_website=1))
    assert score_none > score_poor


def test_high_value_niche_adds_points():
    score_high, _ = _base_score(_lead(niche="restaurant"))
    score_low, _ = _base_score(_lead(niche="bookstore"))
    assert score_high > score_low


def test_phone_adds_points():
    with_phone, _ = _base_score(_lead(phone="5551234567"))
    without_phone, _ = _base_score(_lead(phone=""))
    assert with_phone > without_phone


def test_score_capped_at_90():
    # Max possible base scenario
    score, _ = _base_score(
        _lead(
            website_quality="none",
            has_website=0,
            niche="restaurant",
            google_rating=4.0,
            review_count=100,
            phone="5551234567",
        )
    )
    assert score <= 90


def test_reasons_list_not_empty():
    _, reasons = _base_score(_lead())
    assert len(reasons) > 0
