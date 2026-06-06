"""
Main orchestrator — runs the full pipeline in sequence.

Pipeline
────────
1. Prospect — scrape new leads
2. Score    — AI-assisted lead scoring
3. Outreach — email top leads
4. Follow-up — send queued follow-ups
5. Voice    — trigger OpenClaw for elite leads (if enabled)

Run via: python -m src.orchestrator
     or: python -m src.orchestrator --step prospect
"""

import argparse
import logging
import os
import sys
import time

from rich.logging import RichHandler

from src.config import SCORE_MIN_EMAIL, SCORE_VOICE_THRESHOLD
from src.crm.database import init_db, get_leads, update_lead_status
from src.prospecting.scraper import prospect
from src.prospecting.scorer import score_all_new_leads
from src.outreach.email_composer import compose_outreach_email
from src.outreach.email_sender import send_email, reset_daily_counter
from src.outreach.openclaw import trigger_call, is_eligible
from src.followup.sequence import schedule_followups, process_due_followups
from src.analytics.reporter import weekly_report

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
log = logging.getLogger(__name__)


def step_prospect(yelp_key: str = None) -> None:
    log.info("═══ STEP 1: PROSPECTING ═══")
    count = prospect(yelp_api_key=yelp_key)
    log.info("Prospecting done — %d leads stored.", count)


def step_score() -> None:
    log.info("═══ STEP 2: SCORING ═══")
    stats = score_all_new_leads(use_ai=True)
    log.info(
        "Scoring done — %d leads scored, avg=%.1f, high-value=%d",
        stats["scored"], stats["avg_score"], stats["high_value"],
    )


def step_outreach(dry_run: bool = False) -> None:
    log.info("═══ STEP 3: OUTREACH ═══")
    leads = get_leads(status="scored", min_score=SCORE_MIN_EMAIL, limit=50)
    log.info("Found %d leads ready for outreach (score >= %d)", len(leads), SCORE_MIN_EMAIL)

    sent = 0
    for lead in leads:
        email = lead.get("email")
        if not email:
            log.debug("No email for %s — skipping", lead["business_name"])
            continue

        subject, body = compose_outreach_email(lead)
        success = send_email(
            lead_id=lead["id"],
            to_email=email,
            subject=subject,
            body=body,
            dry_run=dry_run,
        )
        if success:
            schedule_followups(lead["id"])
            sent += 1

    log.info("Outreach done — %d emails sent.", sent)


def step_followup(dry_run: bool = False) -> None:
    log.info("═══ STEP 4: FOLLOW-UPS ═══")
    stats = process_due_followups(dry_run=dry_run)
    log.info("Follow-ups done — %s", stats)


def step_voice() -> None:
    log.info("═══ STEP 5: VOICE OUTREACH (OpenClaw) ═══")
    leads = get_leads(min_score=SCORE_VOICE_THRESHOLD, limit=10)
    triggered = 0
    for lead in leads:
        if lead.get("status") not in ("scored", "emailed"):
            continue
        if trigger_call(lead):
            triggered += 1
    log.info("Voice step done — %d calls triggered.", triggered)


def run_full_pipeline(dry_run: bool = False, yelp_key: str = None) -> None:
    """Run all pipeline steps in sequence."""
    init_db()
    step_prospect(yelp_key=yelp_key)
    step_score()
    step_outreach(dry_run=dry_run)
    step_followup(dry_run=dry_run)
    step_voice()
    log.info("═══ PIPELINE COMPLETE ═══")


def main() -> None:
    parser = argparse.ArgumentParser(description="Curbsite AI Sales Agent")
    parser.add_argument(
        "--step",
        choices=["prospect", "score", "outreach", "followup", "voice", "report", "all"],
        default="all",
        help="Which step to run (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't actually send emails")
    parser.add_argument("--yelp-key", default=os.getenv("YELP_API_KEY"), help="Yelp Fusion API key")
    parser.add_argument("--days", type=int, default=7, help="Days window for report")
    args = parser.parse_args()

    init_db()

    match args.step:
        case "prospect":
            step_prospect(yelp_key=args.yelp_key)
        case "score":
            step_score()
        case "outreach":
            step_outreach(dry_run=args.dry_run)
        case "followup":
            step_followup(dry_run=args.dry_run)
        case "voice":
            step_voice()
        case "report":
            weekly_report(days=args.days)
        case "all":
            run_full_pipeline(dry_run=args.dry_run, yelp_key=args.yelp_key)


if __name__ == "__main__":
    main()
