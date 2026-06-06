"""
Main orchestrator — runs the full appointment-booking pipeline.

Pipeline
────────
1. Prospect  — scrape new leads (Yelp / Google Maps)
2. Score     — AI-assisted lead scoring (0–100)
3. Outreach  — send personalised cold emails with Calendly link + pricing
4. Follow-up — automated Day-3 and Day-7 follow-up sequence
5. Dossier   — generate pre-call brief for every booked appointment

No voice calls. The system automates everything up to the call.
Steele handles the closing. Dossiers give him full context.

Run via:
  python -m src.orchestrator               # full pipeline
  python -m src.orchestrator --dry-run     # no emails sent
  python -m src.orchestrator --step score  # single step
"""

import argparse
import logging
import os

from rich.logging import RichHandler

from src.config import SCORE_MIN_EMAIL
from src.crm.database import init_db, get_leads, update_lead_status
from src.prospecting.scraper import prospect
from src.prospecting.scorer import score_all_new_leads
from src.outreach.email_composer import compose_outreach_email
from src.outreach.email_sender import send_email, reset_daily_counter
from src.followup.sequence import schedule_followups, process_due_followups
from src.crm.dossier import generate_all_booked_dossiers
from src.analytics.reporter import weekly_report

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
log = logging.getLogger(__name__)


# ── Pipeline steps ─────────────────────────────────────────────────────────────

def step_prospect(yelp_key: str = None) -> None:
    log.info("═══ STEP 1: PROSPECTING ═══")
    count = prospect(yelp_api_key=yelp_key)
    log.info("Done — %d leads stored.", count)


def step_score() -> None:
    log.info("═══ STEP 2: SCORING ═══")
    stats = score_all_new_leads(use_ai=True)
    log.info(
        "Done — %d leads scored | avg %.1f | high-value %d",
        stats["scored"], stats["avg_score"], stats["high_value"],
    )


def step_outreach(dry_run: bool = False) -> None:
    log.info("═══ STEP 3: OUTREACH ═══")
    leads = get_leads(status="scored", min_score=SCORE_MIN_EMAIL, limit=50)
    log.info(
        "Found %d leads ready for outreach (score >= %d)",
        len(leads), SCORE_MIN_EMAIL,
    )

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

    log.info("Done — %d emails sent.", sent)


def step_followup(dry_run: bool = False) -> None:
    log.info("═══ STEP 4: FOLLOW-UPS ═══")
    stats = process_due_followups(dry_run=dry_run)
    log.info("Done — %s", stats)


def step_dossiers() -> None:
    log.info("═══ STEP 5: DOSSIER GENERATION ═══")
    count = generate_all_booked_dossiers()
    log.info(
        "Done — %d dossier(s) generated in data/leads/dossiers/", count
    )


def step_report(days: int = 7) -> None:
    log.info("═══ WEEKLY REPORT ═══")
    weekly_report(days=days)


# ── Full pipeline ──────────────────────────────────────────────────────────────

def run_full_pipeline(dry_run: bool = False, yelp_key: str = None) -> None:
    """Run all pipeline steps in sequence."""
    init_db()
    step_prospect(yelp_key=yelp_key)
    step_score()
    step_outreach(dry_run=dry_run)
    step_followup(dry_run=dry_run)
    step_dossiers()
    log.info("═══ PIPELINE COMPLETE ═══")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Curbsite AI Sales Agent")
    parser.add_argument(
        "--step",
        choices=[
            "prospect", "score", "outreach", "followup",
            "dossiers", "report", "all",
        ],
        default="all",
        help="Which step to run (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending emails (safe for testing)",
    )
    parser.add_argument(
        "--yelp-key",
        default=os.getenv("YELP_API_KEY"),
        help="Yelp Fusion API key (optional — falls back to Google scrape)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Days window for the weekly report",
    )
    parser.add_argument(
        "--lead-id",
        type=int,
        help="Generate a dossier for a specific lead ID",
    )
    args = parser.parse_args()

    init_db()

    # Single-lead dossier shortcut
    if args.lead_id:
        from src.crm.dossier import generate_dossier
        dossier = generate_dossier(args.lead_id)
        print(dossier)
        return

    match args.step:
        case "prospect":
            step_prospect(yelp_key=args.yelp_key)
        case "score":
            step_score()
        case "outreach":
            step_outreach(dry_run=args.dry_run)
        case "followup":
            step_followup(dry_run=args.dry_run)
        case "dossiers":
            step_dossiers()
        case "report":
            step_report(days=args.days)
        case "all":
            run_full_pipeline(dry_run=args.dry_run, yelp_key=args.yelp_key)


if __name__ == "__main__":
    main()
