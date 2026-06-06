"""
APScheduler-based cron runner.

Schedule
────────
  Mon–Fri  08:00  — Full pipeline (prospect + score + outreach)
  Daily    09:00  — Process follow-ups
  Mon      07:00  — Weekly report email
  Daily    00:00  — Reset email counter

Run: python -m src.scheduler
"""

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.logging import RichHandler

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
log = logging.getLogger(__name__)


def _pipeline():
    from src.orchestrator import run_full_pipeline
    run_full_pipeline(dry_run=False, yelp_key=os.getenv("YELP_API_KEY"))


def _followups():
    from src.followup.sequence import process_due_followups
    process_due_followups(dry_run=False)


def _report():
    from src.analytics.reporter import weekly_report
    weekly_report(days=7)


def _reset_counter():
    from src.outreach.sender import reset_daily_counter
    reset_daily_counter()


def main():
    from src.crm.database import init_db
    init_db()

    scheduler = BlockingScheduler(timezone="America/Indiana/Indianapolis")

    # Main pipeline Mon–Fri at 8 AM
    scheduler.add_job(
        _pipeline,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=0),
        id="pipeline",
        name="Full pipeline",
        misfire_grace_time=3600,
    )

    # Follow-ups daily at 9 AM
    scheduler.add_job(
        _followups,
        CronTrigger(hour=9, minute=0),
        id="followups",
        name="Follow-up processor",
        misfire_grace_time=3600,
    )

    # Weekly report every Monday at 7 AM
    scheduler.add_job(
        _report,
        CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="report",
        name="Weekly report",
    )

    # Reset email counter at midnight
    scheduler.add_job(
        _reset_counter,
        CronTrigger(hour=0, minute=0),
        id="reset_counter",
        name="Reset daily email counter",
    )

    log.info("Scheduler started. Jobs:")
    for job in scheduler.get_jobs():
        log.info("  %-20s %s", job.id, job.trigger)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
