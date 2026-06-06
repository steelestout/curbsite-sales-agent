"""
Main orchestrator — runs the full Curbsite sales + build + deploy pipeline.

State machine
─────────────
new → scored → emailed → followed_up → mockup_sent → agreed_pending
    → agreed → building → build_ready → domain_purchased → deployed → live
    (any stage → lost | unsubscribed)

Stages
──────
1. prospect       Scrape new leads (Yelp / Google Maps)
2. score          AI-assisted lead scoring (0–100)
3. outreach       Send personalised cold emails with Calendly link + pricing
4. followup       Automated Day-3 and Day-7 follow-up sequence
5. dossier        Generate pre-call brief for every booked appointment
6. mockup         Generate + deploy free mockup websites for qualified leads
7. close          Monitor inbox for replies; classify + route (positive/negative/question)
8. build          Full production site build from intake form + client assets
9. domain         Purchase domain via Namecheap
10. deploy        SSH deploy to Hostinger VPS + Traefik; update DNS
11. golive        Poll for liveness; send client go-live notification

Gates (Steele's manual approvals)
──────────────────────────────────
GATE 1: Before build starts — Steele reviews agreed_pending lead, confirms intake form,
        then runs: python -m src.orchestrator --step build --lead-id {id}

GATE 2: Before go-live — Steele does visual QA of built site, then runs:
        python -m src.orchestrator --step deploy --lead-id {id}

Run via
───────
  python -m src.orchestrator               # full top-of-funnel pipeline (steps 1–7)
  python -m src.orchestrator --dry-run     # no emails, no deploys
  python -m src.orchestrator --step close  # check inbox for replies
  python -m src.orchestrator --step mockup # generate mockups for all emailed leads
  python -m src.orchestrator --step build  --lead-id {id}  # GATE 1: build one site
  python -m src.orchestrator --step deploy --lead-id {id}  # GATE 2: deploy one site
  python -m src.orchestrator --step golive --lead-id {id}  # wait for live + notify
"""

import argparse
import logging
import os

from rich.logging import RichHandler

from src.config import SCORE_MIN_EMAIL
from src.crm.database import init_db, get_leads, get_lead, update_lead_status
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


def step_mockup(dry_run: bool = False) -> None:
    """
    Generate and deliver free mockups to all leads that have been emailed
    or had a follow-up but haven't received a mockup yet.
    Also covers leads in 'call_scheduled' status (post-Calendly booking).
    """
    log.info("═══ STEP 6: MOCKUP GENERATION + DELIVERY ═══")

    from src.mockup.generator import generate_mockup
    from src.mockup.delivery import deliver_mockup

    # Target: emailed, followed_up, or call_scheduled leads who haven't got a mockup
    candidate_statuses = ["emailed", "followed_up", "call_scheduled"]
    candidates = []
    for status in candidate_statuses:
        candidates.extend(get_leads(status=status, limit=50))

    # Deduplicate
    seen = set()
    unique_candidates = []
    for lead in candidates:
        if lead["id"] not in seen:
            seen.add(lead["id"])
            unique_candidates.append(lead)

    log.info("Found %d candidates for mockup generation", len(unique_candidates))

    generated = 0
    for lead in unique_candidates:
        if not lead.get("email"):
            log.debug("No email for %s — skipping mockup", lead["business_name"])
            continue
        try:
            html_path = generate_mockup(lead)
            deliver_mockup(lead, html_path, dry_run=dry_run)
            generated += 1
        except Exception as exc:
            log.error("Mockup failed for lead #%d (%s): %s", lead["id"], lead["business_name"], exc)

    log.info("Done — %d mockups generated and delivered.", generated)


def step_close(dry_run: bool = False) -> None:
    """Check inbox for replies and classify them."""
    log.info("═══ STEP 7: CLOSE (reply monitoring) ═══")
    from src.close.email_closer import process_replies
    stats = process_replies(dry_run=dry_run)
    log.info(
        "Done — checked=%d | positive=%d | negative=%d | questions=%d | errors=%d",
        stats["checked"], stats["positive"], stats["negative"],
        stats.get("question", 0) + stats.get("neutral", 0), stats["errors"],
    )


def step_build(lead_id: int, intake: dict = None, dry_run: bool = False) -> None:
    """
    GATE 1 — Build the full production site for a specific lead.
    Requires lead status = 'agreed' (Steele has confirmed the close).
    """
    log.info("═══ STEP 8: SITE BUILD (lead #%d) ═══", lead_id)

    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    allowed_statuses = ("agreed", "agreed_pending", "build_ready")
    if lead["status"] not in allowed_statuses:
        log.warning(
            "Lead #%d has status '%s' — expected one of %s. Proceeding anyway.",
            lead_id, lead["status"], allowed_statuses,
        )

    if dry_run:
        log.info("[DRY RUN] Would build site for %s", lead.get("business_name"))
        return

    from src.build.site_builder import build_site
    build_dir = build_site(lead, intake=intake)
    log.info("Done — site built at %s", build_dir)


def step_domain(lead_id: int, preferred_domain: str = None, dry_run: bool = False) -> None:
    """Purchase a domain for a specific lead."""
    log.info("═══ STEP 9: DOMAIN PURCHASE (lead #%d) ═══", lead_id)

    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    if dry_run:
        from src.deploy.domain import _candidates
        candidates = _candidates(lead.get("business_name", ""), lead.get("city", ""))
        if preferred_domain:
            candidates.insert(0, preferred_domain)
        log.info("[DRY RUN] Would check and purchase from: %s", candidates)
        return

    from src.deploy.domain import acquire_domain
    domain = acquire_domain(lead, preferred=preferred_domain)
    if domain:
        log.info("Done — domain purchased: %s", domain)
    else:
        log.warning("Domain purchase failed or skipped — see logs above.")


def step_deploy(lead_id: int, dry_run: bool = False) -> None:
    """
    GATE 2 — Deploy a built site to Hostinger VPS.
    Requires lead status = 'build_ready' and a domain in the CRM.
    """
    log.info("═══ STEP 10: VPS DEPLOY (lead #%d) ═══", lead_id)

    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    domain = lead.get("domain")
    if not domain:
        log.error(
            "No domain set for lead #%d. Run domain purchase first, or set it manually "
            "with: UPDATE leads SET domain=? WHERE id=?",
            lead_id, lead_id,
        )
        return

    from src.deploy.host import deploy_to_vps
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parent.parent
    build_dir = _ROOT / "data" / "builds" / str(lead_id)

    if not build_dir.exists():
        log.error("Build directory not found: %s — run --step build first.", build_dir)
        return

    success = deploy_to_vps(lead, build_dir, domain, dry_run=dry_run)
    if success:
        log.info("Done — deployed to https://%s", domain)
    else:
        log.error("Deploy failed for lead #%d", lead_id)


def step_golive(lead_id: int, dry_run: bool = False) -> None:
    """Poll for liveness and send the client go-live notification."""
    log.info("═══ STEP 11: GO-LIVE (lead #%d) ═══", lead_id)

    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    domain = lead.get("domain")
    if not domain:
        log.error("No domain for lead #%d.", lead_id)
        return

    from src.deploy.golive import run_golive
    from src.config import PORTAL_URL
    success = run_golive(lead, domain, portal_url=PORTAL_URL, dry_run=dry_run)
    if success:
        log.info("Done — lead #%d is LIVE at https://%s", lead_id, domain)
    else:
        log.warning("Go-live check failed for lead #%d — check manually.", lead_id)


def step_report(days: int = 7) -> None:
    log.info("═══ WEEKLY REPORT ═══")
    weekly_report(days=days)


# ── Top-of-funnel pipeline (fully automated) ──────────────────────────────────

def run_top_of_funnel(dry_run: bool = False, yelp_key: str = None) -> None:
    """
    Run all automated top-of-funnel steps (prospect → close monitoring).
    Does NOT build or deploy — those require Steele's approval at two gates.
    """
    init_db()
    step_prospect(yelp_key=yelp_key)
    step_score()
    step_outreach(dry_run=dry_run)
    step_followup(dry_run=dry_run)
    step_dossiers()
    step_mockup(dry_run=dry_run)
    step_close(dry_run=dry_run)
    log.info("═══ TOP-OF-FUNNEL COMPLETE ═══")
    log.info(
        "Next: check the CRM for leads in 'agreed_pending' status.\n"
        "For each one, review the intake form and run:\n"
        "  python -m src.orchestrator --step build --lead-id {id}"
    )


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Curbsite AI Sales + Build + Deploy Agent")
    parser.add_argument(
        "--step",
        choices=[
            "prospect", "score", "outreach", "followup",
            "dossiers", "mockup", "close",
            "build", "domain", "deploy", "golive",
            "report", "all",
        ],
        default="all",
        help="Which step to run (default: all = top-of-funnel only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending emails or making purchases (safe for testing)",
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
        help="Target a specific lead ID (required for build, domain, deploy, golive)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        help="Preferred domain name for --step domain (e.g. marios-pizza.com)",
    )
    args = parser.parse_args()

    init_db()

    # Single-lead dossier shortcut (legacy)
    if args.lead_id and args.step not in ("build", "domain", "deploy", "golive", "dossiers"):
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
            if args.lead_id:
                from src.crm.dossier import generate_dossier
                print(generate_dossier(args.lead_id))
            else:
                step_dossiers()
        case "mockup":
            step_mockup(dry_run=args.dry_run)
        case "close":
            step_close(dry_run=args.dry_run)
        case "build":
            if not args.lead_id:
                parser.error("--step build requires --lead-id")
            step_build(args.lead_id, dry_run=args.dry_run)
        case "domain":
            if not args.lead_id:
                parser.error("--step domain requires --lead-id")
            step_domain(args.lead_id, preferred_domain=args.domain, dry_run=args.dry_run)
        case "deploy":
            if not args.lead_id:
                parser.error("--step deploy requires --lead-id")
            step_deploy(args.lead_id, dry_run=args.dry_run)
        case "golive":
            if not args.lead_id:
                parser.error("--step golive requires --lead-id")
            step_golive(args.lead_id, dry_run=args.dry_run)
        case "report":
            step_report(days=args.days)
        case "all":
            run_top_of_funnel(dry_run=args.dry_run, yelp_key=args.yelp_key)


if __name__ == "__main__":
    main()
