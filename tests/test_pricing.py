"""Tests for tier recommendation and pricing logic."""

import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")

from src.outreach.pricing import recommend_tier, format_pricing_blurb, PRICE_ENTRY, PRICE_MID, PRICE_TOP


def _lead(**kwargs):
    base = {
        "id": 1,
        "business_name": "Test Biz",
        "city": "Kokomo",
        "state": "IN",
        "niche": "photography",
        "website_quality": "none",
        "has_website": 0,
        "google_rating": 4.2,
        "review_count": 20,
        "score": 55,
    }
    base.update(kwargs)
    return base


def test_entry_tier_for_photographer():
    rec = recommend_tier(_lead(niche="photography", review_count=15, score=50))
    assert rec.tier == "entry"
    assert rec.price == PRICE_ENTRY
    assert PRICE_ENTRY > 0


def test_mid_tier_for_restaurant():
    rec = recommend_tier(_lead(niche="restaurant", review_count=40, score=60))
    assert rec.tier == "mid"
    assert rec.price == PRICE_MID


def test_top_tier_for_contractor():
    rec = recommend_tier(_lead(niche="contractor", review_count=80, score=75))
    assert rec.tier == "top"
    assert rec.price == PRICE_TOP


def test_top_tier_for_high_score_established_biz():
    # Even a non-top niche should get Top if reviews >= 100 and weak web
    rec = recommend_tier(_lead(niche="bakery", review_count=120, website_quality="none", score=72))
    assert rec.tier == "top"


def test_tier_recommendation_has_headline_features():
    rec = recommend_tier(_lead())
    assert len(rec.headline_features) == 3


def test_tier_recommendation_has_pitch_angle():
    rec = recommend_tier(_lead())
    assert rec.pitch_angle and len(rec.pitch_angle) > 10


def test_format_pricing_blurb_includes_tier_label():
    rec = recommend_tier(_lead(niche="restaurant"))
    blurb = format_pricing_blurb(rec, include_care=True)
    assert rec.label in blurb
    assert "care plan" in blurb.lower()


def test_email_mention_includes_price():
    rec = recommend_tier(_lead())
    assert "$" in rec.email_mention
    assert str(rec.price) in rec.email_mention
