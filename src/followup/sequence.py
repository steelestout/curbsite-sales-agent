"""
Follow-up sequence manager.

Sequence (days after initial email):
  Step 1 — Day 3:  Short observation + one value tip
  Step 2 — Day 7:  Final touch, low-pressure, leave door open

After step 2 with no reply → status = 'lost'
If a Calendly booking comes in at any point → status = 'call_scheduled'
  (handled by the webhook receiver or manual update)

Weekly cap: MAX_FOLLOWUPS_PER_WEEK is checked before each batch.
"""

import logging
from datetime import datetime, timedelta

from src.config import MAX_FOLLOWUPS_PER_WEEK
from src.crm.database import (
    enqueue_followup,
    get_due_followups,
    get_leads,
    mark_followup_sent,
    update_lead_status,
)
from src.outreach.email_composer import compose_followup_email
from src.outreach.sender import send_email

log = logging.getLogger(__name__)

FOLLOWUP_DAYS = {1: 3, 2: 7}   # step → days after initial email

# Simple in-process weekly counter (resets on restart; good enough)
_sent_this_week = 0


def _reset_weekly_counter() -> None:
    global _sent_this_week
    _sent_this_week = 0


def schedule_followups(lead_id: int) -> None:
    """
    Enqueue all follow-up steps for a newly-emailed lead.
    Call immediately after the initial email is sent.
    """
    now = datetime.utcnow()
    for step, days in FOLLOWUP_DAYS.items():
        scheduled = (now + timedelta(days=days)).isoformat()
        enqueue_followup(lead_id, step, scheduled)
        log.debug(
            "Scheduled step-%d follow-up for lead #%d on %s", step, lead_id, scheduled
        )


def process_due_followups(dry_run: bool = False) -> dict:
    """
    Send all overdue follow-up emails.
    Respects MAX_FOLLOWUPS_PER_WEEK cap.
    Returns stats dict.
    """
    global _sent_this_week

    due = get_due_followups()
    if not due:
        log.info("No follow-ups due right now.")
        return {"processed": 0, "sent": 0, "skipped": 0, "failed": 0}

    log.info("Processing %d due follow-ups...", len(due))
    sent = skipped = failed = 0

    for item in due:
        # Skip if lead has already booked or converted
        if item.get("status") in ("call_scheduled", "won", "unsubscribed"):
            log.debug(
                "Lead #%d status=%s — skipping follow-up", item["lead_id"], item.get("status")
            )
            mark_followup_sent(item["id"])
            skipped += 1
            continue

        # Weekly cap
        if _sent_this_week >= MAX_FOLLOWUPS_PER_WEEK:
            log.warning(
                "Weekly follow-up cap (%d) reached — stopping.", MAX_FOLLOWUPS_PER_WEEK
            )
            break

        email = item.get("email")
        if not email:
            log.warning(
                "Lead #%d has no email — skipping follow-up step %d",
                item["lead_id"],
                item["sequence_step"],
            )
            mark_followup_sent(item["id"])
            skipped += 1
            continue

        lead = {
            "id": item["lead_id"],
            "business_name": item["business_name"],
            "email": email,
            "owner_name": item.get("owner_name"),
            "niche": item.get("niche"),
            "city": item.get("city"),
            "website_quality": item.get("website_quality", "none"),
            "score": item.get("score", 0),
        }

        step = item["sequence_step"]
        subject, body = compose_followup_email(lead, step)

        success = send_email(
            lead_id=item["lead_id"],
            to_email=email,
            subject=subject,
            body=body,
            dry_run=dry_run,
        )

        if success:
            mark_followup_sent(item["id"])
            _sent_this_week += 1
            sent += 1

            if step >= max(FOLLOWUP_DAYS.keys()):
                # Final step sent — mark lost if still no reply
                update_lead_status(
                    item["lead_id"],
                    "lost",
                    notes="Completed full follow-up sequence with no reply.",
                )
                log.info("Lead #%d completed sequence — marked lost.", item["lead_id"])
            else:
                update_lead_status(item["lead_id"], "followed_up")
        else:
            failed += 1

    return {
        "processed": len(due),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }
