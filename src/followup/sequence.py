"""
Follow-up sequence manager.

Sequence (days after initial email):
  Step 1 — Day 3:  Short friendly check-in
  Step 2 — Day 7:  Final nudge, leave door open

After step 2 with no reply → status = 'lost' (for now)
"""

import logging
from datetime import datetime, timedelta

from src.crm.database import (
    enqueue_followup,
    get_due_followups,
    get_leads,
    mark_followup_sent,
    update_lead_status,
)
from src.outreach.email_composer import compose_followup_email
from src.outreach.email_sender import send_email

log = logging.getLogger(__name__)

FOLLOWUP_DAYS = {1: 3, 2: 7}   # step -> days after initial email


def schedule_followups(lead_id: int) -> None:
    """
    Enqueue all follow-up steps for a newly-emailed lead.
    Called immediately after the initial email is sent.
    """
    now = datetime.utcnow()
    for step, days in FOLLOWUP_DAYS.items():
        scheduled = (now + timedelta(days=days)).isoformat()
        enqueue_followup(lead_id, step, scheduled)
        log.debug("Scheduled step %d follow-up for lead #%d on %s", step, lead_id, scheduled)


def process_due_followups(dry_run: bool = False) -> dict:
    """
    Send all overdue follow-up emails. Returns stats dict.
    """
    due = get_due_followups()
    if not due:
        log.info("No follow-ups due right now.")
        return {"processed": 0, "sent": 0, "failed": 0}

    log.info("Processing %d due follow-ups...", len(due))
    sent = 0
    failed = 0

    for item in due:
        lead = {
            "id": item["lead_id"],
            "business_name": item["business_name"],
            "email": item["email"],
            "owner_name": item["owner_name"],
            "niche": item["niche"],
            "city": item["city"],
        }

        step = item["sequence_step"]
        email = item.get("email")
        if not email:
            log.warning("Lead #%d has no email — skipping follow-up step %d", item["lead_id"], step)
            mark_followup_sent(item["id"])
            continue

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
            sent += 1

            # After final step, move lead to 'lost' if still no reply
            if step >= max(FOLLOWUP_DAYS.keys()):
                update_lead_status(
                    item["lead_id"],
                    "lost",
                    notes="No reply after full sequence",
                )
                log.info("Lead #%d marked lost after full sequence.", item["lead_id"])
            else:
                update_lead_status(item["lead_id"], "followed_up")
        else:
            failed += 1

    return {"processed": len(due), "sent": sent, "failed": failed}
