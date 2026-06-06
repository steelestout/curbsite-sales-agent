"""
Voice calling is intentionally disabled.
These tests verify the stub returns the right values
and does NOT accidentally enable calls.
"""

import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("SMTP_USER", "test@example.com")
os.environ.setdefault("SMTP_PASS", "testpass")

from src.outreach.openclaw import is_eligible, VOICE_ENABLED


def test_voice_disabled_constant():
    """VOICE_ENABLED must always be False."""
    assert VOICE_ENABLED is False


def test_is_eligible_always_false():
    """is_eligible must return False regardless of lead score."""
    for score in [0, 50, 85, 95, 100]:
        lead = {"id": 1, "score": score, "phone": "5551234567"}
        assert is_eligible(lead) is False, f"Expected False for score={score}"


def test_trigger_call_raises():
    """trigger_call must raise NotImplementedError, not silently succeed."""
    from src.outreach.openclaw import trigger_call
    with pytest.raises(NotImplementedError):
        trigger_call({"id": 1, "score": 99})
