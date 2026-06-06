"""
Inbox warming schedule — enforces graduated daily limits for new sending accounts.

New accounts sent at full volume immediately get flagged by Gmail/GSuite.
This module caps daily sends based on the account's warmup_day counter.

Schedule:
  Week 1  (days  1–7):   max  5 emails/day
  Week 2  (days  8–14):  max 15 emails/day
  Week 3  (days 15–21):  max 30 emails/day
  Week 4+ (days 22+):    max 50 emails/day  ← full production volume

warmup_day is stored per account in the SENDER_ACCOUNTS config.
Run `python -m src.outreach.warmup --tick <email>` once daily to increment it.
"""

import logging

log = logging.getLogger(__name__)

# (first_day, last_day_inclusive, daily_limit)
_SCHEDULE: list[tuple[int, int, int]] = [
    (1,  7,  5),
    (8,  14, 15),
    (15, 21, 30),
    (22, 9999, 50),
]

_FULL_SEND_DAY = 22  # Day from which full outreach volume is unlocked


def get_warmup_limit(warmup_day: int) -> int:
    """Return the daily email cap for an account on the given warmup_day."""
    for min_d, max_d, limit in _SCHEDULE:
        if min_d <= warmup_day <= max_d:
            return limit
    return 50


def is_warmed(warmup_day: int) -> bool:
    """True if the account has completed warmup and can send at full volume."""
    return warmup_day >= _FULL_SEND_DAY


def warmup_status(account: dict) -> dict:
    """
    Return a status summary for display in the dashboard.
    account must have 'email' and 'warmup_day' keys.
    """
    day = account.get("warmup_day", 1)
    limit = get_warmup_limit(day)
    warmed = is_warmed(day)
    week = (day - 1) // 7 + 1
    days_remaining = max(0, _FULL_SEND_DAY - day)
    return {
        "email": account.get("email", ""),
        "warmup_day": day,
        "week": week,
        "daily_limit": limit,
        "is_warmed": warmed,
        "days_to_full": days_remaining,
    }


def check_and_warn(account: dict) -> int:
    """
    Return the daily limit for this account and warn if not yet fully warmed.
    account must have 'email' and 'warmup_day' keys.
    """
    day = account.get("warmup_day", 1)
    limit = get_warmup_limit(day)
    if not is_warmed(day):
        log.warning(
            "Account %s is warming up (day %d / week %d) — capped at %d emails/day. "
            "%d days until full volume. Do not bypass this limit.",
            account.get("email", "?"), day, (day - 1) // 7 + 1, limit,
            max(0, _FULL_SEND_DAY - day),
        )
    return limit


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json
    import os

    if "--status" in sys.argv:
        raw = os.getenv("SENDER_ACCOUNTS", "[]")
        try:
            accounts = json.loads(raw)
        except Exception:
            accounts = []
        if not accounts:
            print("No SENDER_ACCOUNTS configured. Add them to .env first.")
            sys.exit(1)
        for acct in accounts:
            s = warmup_status(acct)
            status = "READY" if s["is_warmed"] else f"WARMING ({s['days_to_full']} days left)"
            print(f"  {s['email']}: day {s['warmup_day']}, limit {s['daily_limit']}/day — {status}")
