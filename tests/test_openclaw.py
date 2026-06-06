"""Tests for OpenClaw gating logic."""

import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")


def test_openclaw_disabled_by_default(monkeypatch):
    """OpenClaw must be OFF unless explicitly enabled."""
    monkeypatch.setattr("src.outreach.openclaw.OPENCLAW_ENABLED", False)
    from src.outreach.openclaw import is_eligible
    lead = {"id": 1, "score": 95, "phone": "5551234567"}
    assert is_eligible(lead) is False


def test_openclaw_enabled_but_score_too_low(monkeypatch):
    monkeypatch.setattr("src.outreach.openclaw.OPENCLAW_ENABLED", True)
    monkeypatch.setattr("src.outreach.openclaw.OPENCLAW_API_KEY", "key123")
    monkeypatch.setattr("src.outreach.openclaw.OPENCLAW_AGENT_ID", "agent123")
    monkeypatch.setattr("src.outreach.openclaw.SCORE_VOICE_THRESHOLD", 85)
    from importlib import reload
    import src.outreach.openclaw as oc
    reload(oc)
    from src.outreach.openclaw import is_eligible
    lead = {"id": 1, "score": 70, "phone": "5551234567"}
    assert is_eligible(lead) is False


def test_openclaw_eligible_when_all_conditions_met(monkeypatch):
    monkeypatch.setattr("src.outreach.openclaw.OPENCLAW_ENABLED", True)
    monkeypatch.setattr("src.outreach.openclaw.OPENCLAW_API_KEY", "key123")
    monkeypatch.setattr("src.outreach.openclaw.OPENCLAW_AGENT_ID", "agent123")
    monkeypatch.setattr("src.outreach.openclaw.SCORE_VOICE_THRESHOLD", 85)
    from src.outreach.openclaw import is_eligible
    lead = {"id": 1, "score": 90, "phone": "5551234567"}
    assert is_eligible(lead) is True
