"""
Main orchestrator — runs the full Curbsite sales + build + deploy pipeline.

State machine
─────────────
new → scored → mockup_ready → contacted (postcard) → emailed → followed_up → mockup_sent
    → agreed_pending → agreed → building → build_ready
    → domain_purchased → deployed → live
    (any stage → lost | unsubscribed)

Stages
──────
1. prospect       Scrape new leads (Yelp / Google Maps)
2. score          AI-assisted lead scoring + PageSpeed bonus (0–100)
2b. mockup        Pre-outreach: generate mockup immediately after scoring
3. outreach       Send personalised cold emails with mockup link + Calendly CTA
4. followup       Automated Day-3 and Day-7 follow-up sequence
5. dossier        Generate pre-call brief for every booked appointment
6. close          Monitor inbox for replies; classify + route
7. build          Full production site build from intake form + client assets
                  → emails Steele a preview with Approve / Request Changes buttons
8. domain         Purchase domain via Namecheap
9. deploy         Deploy site — Track A (Hetzner VPS) or Track B (zip handoff)
10. golive        Poll for liveness; send client go-live notification

Post-launch automation (run daily via scheduler)
─────────────────────────────────────────────────
  reviews         14-day review request + 30-day reminder
  referrals       30-day referral drip email

Deployment tracks
─────────────────
Track A — Client signed up for maintenance plan:
  Provision dedicated Hetzner VPS → SSH deploy → update DNS → go-live

Track B — No maintenance plan (client hosts their own):
  Build zip → email to client with README and hosting instructions

Gates (Steele's approvals)
──────────────────────────
GATE 1: Build trigger — runs: python -m src.orchestrator --step build --lead-id {id}
        (or auto-triggered by Stripe 50% deposit webhook)

GATE 2: Preview approval — Steele clicks "Approve" in email or dashboard
        → client receives preview + payment link
        (or manually: python -m src.orchestrator --step approve-build --lead-id {id})

GATE 3: Deploy — runs: python -m src.orchestrator --step deploy --lead-id {id}
        (or auto-triggered by Stripe final payment webhook)

Run via
───────
  python -m src.orchestrator                         # full top-of-funnel (steps 1–6)
  python -m src.orchestrator --dry-run               # no emails, no deploys
  python -m src.orchestrator --step close            # check inbox for replies
  python -m src.orchestrator --step mockup           # generate mockups for scored leads
  python -m src.orchestrator --step postcard         # send physical postcards via Lob.com
  python -m src.orchestrator --step build --lead-id {id}          # GATE 1
  python -m src.orchestrator --step approve-build --lead-id {id}  # GATE 2 (manual bypass)
  python -m src.orchestrator --step domain    --lead-id {id}      # purchase domain
  python -m src.orchestrator --step vps-provision --lead-id {id}  # Track A: provision VPS
  python -m src.orchestrator --step deploy    --lead-id {id}      # GATE 3: deploy site
  python -m src.orchestrator --step handoff   --lead-id {id}      # Track B: zip handoff
  python -m src.orchestrator --step golive    --lead-id {id}      # wait for live + notify
  python -m src.orchestrator --step reviews                        # process review requests
  python -m src.orchestrator --step referrals                      # process referral drip
"""

import argparse
import json
import logging
import os
import time

from rich.logging import RichHandler

from src.config import SCORE_MIN_EMAIL
from src.crm.database import init_db, get_leads, get_lead, update_lead_status
from src.prospecting.scraper import prospect
from src.prospecting.scorer import score_all_new_leads
from src.outreach.email_composer import compose_outreach_email
from src.outreach.sender import send_email, reset_daily_counter
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

def step_prospect(yelp_key: str = None, google_key: str = None) -> None:
    log.info("═══ STEP 1: PROSPECTING ═══")
    count = prospect(yelp_api_key=yelp_key, google_api_key=google_key)
    log.info("Done — %d leads stored.", count)


def step_score() -> None:
    log.info("═══ STEP 2: SCORING ═══")
    stats = score_all_new_leads(use_ai=True)
    log.info(
        "Done — %d leads scored | avg %.1f | high-value %d",
        stats["scored"], stats["avg_score"], stats["high_value"],
    )


def step_enrich(dry_run: bool = False) -> None:
    """Query Facebook for email addresses on no-website, no-email scored leads."""
    log.info("═══ STEP 2c: FACEBOOK ENRICHMENT ═══")
    from datetime import datetime as _dt
    from src.enrichment.facebook_scraper import enrich_lead_facebook_sync
    from src.crm.database import get_conn

    _DAILY_LIMIT = 50

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, business_name, city, state, social_links, phone
               FROM leads
               WHERE (website IS NULL OR website = '')
                 AND (email IS NULL OR email = '')
                 AND status = 'scored'
               ORDER BY score DESC
               LIMIT ?""",
            (_DAILY_LIMIT,),
        ).fetchall()

    leads = [dict(r) for r in rows]
    log.info("Found %d no-website, no-email leads to enrich via Facebook", len(leads))

    enriched = 0
    found_emails = 0
    for lead in leads:
        if dry_run:
            log.info("[DRY RUN] Would enrich: %s, %s %s", lead["business_name"], lead["city"], lead["state"])
            continue
        try:
            result = enrich_lead_facebook_sync(
                lead["business_name"],
                lead.get("city") or "",
                lead.get("state") or "",
            )
            if result.get("email") or result.get("facebook_url") or result.get("phone"):
                now = _dt.utcnow().isoformat()
                updates: dict = {"updated_at": now}

                if result.get("email"):
                    updates["email"] = result["email"]
                    found_emails += 1

                # Only overwrite phone if we don't already have one
                if result.get("phone") and not lead.get("phone"):
                    updates["phone"] = result["phone"]

                if result.get("facebook_url"):
                    try:
                        links = json.loads(lead.get("social_links") or "{}")
                    except Exception:
                        links = {}
                    links["facebook"] = result["facebook_url"]
                    updates["social_links"] = json.dumps(links)

                with get_conn() as conn:
                    set_clause = ", ".join(f"{k}=?" for k in updates)
                    conn.execute(
                        f"UPDATE leads SET {set_clause} WHERE id=?",
                        [*updates.values(), lead["id"]],
                    )
                enriched += 1
                log.info(
                    "Enriched lead #%d (%s) — email: %s | FB: %s",
                    lead["id"], lead["business_name"],
                    result.get("email"), result.get("facebook_url"),
                )
        except Exception as exc:
            log.warning(
                "FB enrichment failed for lead #%d (%s): %s",
                lead["id"], lead["business_name"], exc,
            )
        time.sleep(2)

    log.info(
        "Done — %d leads processed | %d enriched | %d emails found",
        len(leads), enriched, found_emails,
    )


def step_outreach(dry_run: bool = False) -> None:
    log.info("═══ STEP 3: OUTREACH ═══")
    # Also pick up mockup_ready leads (scored + mockup generated before email)
    leads_scored = get_leads(status="scored", min_score=SCORE_MIN_EMAIL, limit=50)
    leads_mockup_ready = get_leads(status="mockup_ready", min_score=SCORE_MIN_EMAIL, limit=50)
    lead_ids_seen = {l["id"] for l in leads_scored}
    leads = leads_scored + [l for l in leads_mockup_ready if l["id"] not in lead_ids_seen]
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


def step_mockup(dry_run: bool = False, pre_outreach: bool = False) -> None:
    """
    Generate free mockups for leads.

    Two modes:
    1. Pre-outreach (pre_outreach=True): called right after scoring, before any email
       is sent. Generates mockup and sets status to 'mockup_ready'. The URL gets
       embedded in the very first cold email as the hook.
    2. Post-outreach (default): generates + delivers mockups to leads who have been
       emailed but haven't received a separate mockup delivery email yet. Also covers
       call_scheduled leads.
    """
    if pre_outreach:
        log.info("═══ STEP 2b: PRE-OUTREACH MOCKUP GENERATION ═══")
    else:
        log.info("═══ STEP 6 (manual): MOCKUP GENERATION + DELIVERY ═══")

    from src.mockup.generator import generate_mockup
    from src.mockup.delivery import deliver_mockup

    if pre_outreach:
        # Only generate — don't send a separate delivery email.
        # The URL will be picked up by compose_outreach_email() via _get_mockup_url().
        candidate_statuses = ["scored"]
        deliver = False
    else:
        # Full generate + deliver to leads who have been emailed but not yet had a
        # dedicated mockup delivery email.
        candidate_statuses = ["emailed", "followed_up", "call_scheduled"]
        deliver = True

    candidates = []
    for status in candidate_statuses:
        candidates.extend(get_leads(status=status, min_score=SCORE_MIN_EMAIL, limit=50))

    # Deduplicate
    seen: set = set()
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
            if deliver:
                deliver_mockup(lead, html_path, dry_run=dry_run)
            else:
                # Pre-outreach: just update status so outreach picks it up
                if not dry_run:
                    update_lead_status(lead["id"], "mockup_ready")
                log.info(
                    "Pre-outreach mockup generated for lead #%d (%s) — URL will appear in first email.",
                    lead["id"], lead.get("business_name"),
                )
            generated += 1
        except Exception as exc:
            log.error(
                "Mockup failed for lead #%d (%s): %s",
                lead["id"], lead["business_name"], exc,
            )

    log.info("Done — %d mockups generated.", generated)


def step_postcard(dry_run: bool = None) -> None:
    """
    Send physical postcards via Lob.com to mockup_ready leads that have a mailing
    address and a deployed mockup URL but haven't been mailed yet.
    """
    from src.config import LOB_LIVE_MODE
    if dry_run is None:
        dry_run = not LOB_LIVE_MODE

    log.info("═══ STEP 3b: POSTCARD OUTREACH (dry_run=%s) ═══", dry_run)

    from datetime import datetime as _dt
    from src.outreach.postcard import send_postcard_batch
    from src.crm.database import get_conn

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT l.*, m.netlify_url AS mockup_url
               FROM leads l
               JOIN mockups m ON m.lead_id = l.id
               WHERE l.status = 'mockup_ready'
                 AND l.postcard_id IS NULL
                 AND l.address_line1 IS NOT NULL
                 AND l.address_line1 != ''
                 AND m.netlify_url IS NOT NULL
               ORDER BY l.score DESC
               LIMIT 50"""
        ).fetchall()

    leads = [dict(r) for r in rows]
    log.info("Found %d leads ready for postcard outreach", len(leads))

    if not leads:
        log.info("No postcard-eligible leads — skipping.")
        return

    def _get_mockup_url(lead: dict) -> str:
        return lead["mockup_url"]

    results = send_postcard_batch(leads, _get_mockup_url, dry_run=dry_run)

    # Stamp postcard_id and postcard_sent_at on each mailed lead
    if not dry_run:
        now = _dt.utcnow().isoformat()
        for lead, postcard_id in zip(leads, results["ids"]):
            with get_conn() as conn:
                conn.execute(
                    "UPDATE leads SET postcard_id=?, postcard_sent_at=?, status='contacted', updated_at=? WHERE id=?",
                    (postcard_id, now, now, lead["id"]),
                )

    log.info(
        "Done — sent=%d | failed=%d | dry_run=%s",
        results["sent"], results["failed"], results["dry_run"],
    )


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
    After build completes, emails Steele a preview with Approve/Request Changes buttons.
    """
    log.info("═══ STEP 8: SITE BUILD (lead #%d) ═══", lead_id)

    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    allowed_statuses = ("agreed", "agreed_pending", "build_ready", "building")
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
    log.info("Site built at %s", build_dir)

    # Email Steele a preview with approve / request-changes buttons (GATE 2)
    try:
        from src.notifications.client_status import request_steele_approval
        request_steele_approval(lead_id)
        log.info("Steele approval email sent for lead #%d — check your inbox.", lead_id)
    except Exception as exc:
        log.error("Could not send Steele approval email: %s", exc)

    log.info("Done — lead #%d awaiting Steele approval before client sees preview.", lead_id)


def step_approve_build(lead_id: int, dry_run: bool = False) -> None:
    """
    GATE 2 (manual CLI bypass) — Approve a built site and send client the review email.
    Normally triggered by Steele clicking the approval link in his email or the dashboard.
    """
    log.info("═══ APPROVE BUILD (lead #%d) ═══", lead_id)

    if dry_run:
        log.info("[DRY RUN] Would approve build for lead #%d", lead_id)
        return

    from src.crm.database import get_conn
    from src.notifications.client_status import notify_review_ready
    from src.config import DASHBOARD_URL, PORTAL_URL
    import datetime

    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET build_approved=1, updated_at=? WHERE id=?",
            (datetime.datetime.utcnow().isoformat(), lead_id),
        )
    update_lead_status(lead_id, "build_ready", notes="Approved by Steele (CLI)")

    preview_url = f"{DASHBOARD_URL}/preview/{lead_id}/"
    payment_url = lead.get("stripe_payment_url") or f"{PORTAL_URL}/pay/{lead_id}"
    notify_review_ready(lead, preview_url, payment_url)
    log.info("Done — review-ready email sent to client for lead #%d", lead_id)


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


def step_vps_provision(lead_id: int, dry_run: bool = False) -> None:
    """
    Track A only — Provision a dedicated Hetzner VPS for this client.
    Run this BEFORE step_deploy for Track A clients.
    """
    log.info("═══ VPS PROVISION (lead #%d) ═══", lead_id)

    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    domain = lead.get("domain")
    if not domain:
        log.error(
            "No domain for lead #%d. Run --step domain first.",
            lead_id,
        )
        return

    if dry_run:
        from src.deploy.vps_provisioner import _select_server_type, _SERVER_TYPES
        stype = _select_server_type(lead)
        specs = _SERVER_TYPES[stype]
        log.info(
            "[DRY RUN] Would provision %s VPS (%s: %d vCPU / %dGB RAM / ~$%d/mo) for %s",
            stype, specs["type"], specs["cpu"], specs["ram"], specs["price_mo"],
            lead.get("business_name"),
        )
        return

    from src.deploy.vps_provisioner import provision_vps
    ip = provision_vps(lead, domain)
    if ip:
        log.info("Done — VPS provisioned at %s for %s", ip, domain)
    else:
        log.error("VPS provisioning failed or skipped — check logs / set HETZNER_API_TOKEN.")


def step_deploy(lead_id: int, track: str = None, dry_run: bool = False) -> None:
    """
    GATE 2 — Deploy a built site.

    Track A (maintenance plan): SSH deploy to Hetzner VPS (run vps-provision first).
    Track B (no maintenance): Zip + email handoff to client.

    Auto-selects based on lead.care_plan if track is not specified.
    """
    lead = get_lead(lead_id)
    if not lead:
        log.error("Lead #%d not found.", lead_id)
        return

    domain = lead.get("domain")
    if not domain:
        log.error(
            "No domain set for lead #%d. Run --step domain first, or set it manually.",
            lead_id,
        )
        return

    from pathlib import Path as _Path
    _ROOT = _Path(__file__).resolve().parent.parent
    build_dir = _ROOT / "data" / "builds" / str(lead_id)

    if not build_dir.exists():
        log.error("Build directory not found: %s — run --step build first.", build_dir)
        return

    # Determine track
    if not track:
        track = "a" if lead.get("care_plan") else "b"
        log.info(
            "Auto-selected Track %s for lead #%d (%s care_plan)",
            track.upper(), lead_id,
            "has" if track == "a" else "no",
        )

    if track.lower() == "a":
        log.info("═══ STEP DEPLOY — TRACK A: VPS DEPLOY (lead #%d) ═══", lead_id)
        from src.deploy.host import deploy_to_vps
        success = deploy_to_vps(lead, build_dir, domain, dry_run=dry_run)
        if success:
            log.info("Done — deployed to https://%s", domain)
        else:
            log.error("Deploy failed for lead #%d", lead_id)
    else:
        log.info("═══ STEP DEPLOY — TRACK B: ZIP HANDOFF (lead #%d) ═══", lead_id)
        from src.deploy.handoff import deliver_handoff
        zip_path = deliver_handoff(lead, build_dir, domain, dry_run=dry_run)
        if zip_path:
            log.info("Done — handoff zip sent: %s", zip_path.name)
        else:
            log.error("Handoff failed for lead #%d", lead_id)


def step_handoff(lead_id: int, dry_run: bool = False) -> None:
    """Track B shortcut — explicitly run the zip handoff for a specific lead."""
    step_deploy(lead_id, track="b", dry_run=dry_run)


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
        # Stamp golive_at so review/referral timers start
        import datetime
        from src.crm.database import get_conn
        with get_conn() as conn:
            conn.execute(
                "UPDATE leads SET golive_at=?, updated_at=? WHERE id=?",
                (datetime.datetime.utcnow().isoformat(), datetime.datetime.utcnow().isoformat(), lead_id),
            )
        if not dry_run:
            lead_fresh = get_lead(lead_id)
            # Send site-live email to client
            try:
                from src.notifications.client_status import notify_site_live
                notify_site_live(lead_fresh, f"https://{domain}")
            except Exception as exc:
                log.error("Could not send site-live email: %s", exc)
            # Sync live status to portal — "Your site is live! 🎉"
            try:
                from src.build.portal_sync import sync_lead_status_to_portal
                sync_lead_status_to_portal(lead_fresh)
            except Exception as exc:
                log.error("Portal live status sync failed for lead #%d: %s", lead_id, exc)
        log.info("Done — lead #%d is LIVE at https://%s", lead_id, domain)
    else:
        log.warning("Go-live check failed for lead #%d — check manually.", lead_id)


def step_reviews(dry_run: bool = False) -> None:
    """Process 14-day review requests and 30-day reminders for live clients."""
    log.info("═══ REVIEW REQUESTS ═══")
    from src.reviews.request import process_review_requests
    stats = process_review_requests(dry_run=dry_run)
    log.info("Done — requests: %d | reminders: %d | errors: %d",
             stats["requests_sent"], stats["reminders_sent"], stats["errors"])


def step_referrals(dry_run: bool = False) -> None:
    """Process 30-day referral drip emails for live clients."""
    log.info("═══ REFERRAL DRIP ═══")
    from src.referrals.drip import process_referral_drip
    stats = process_referral_drip(dry_run=dry_run)
    log.info("Done — sent: %d | errors: %d", stats["sent"], stats["errors"])


def step_report(days: int = 7) -> None:
    log.info("═══ WEEKLY REPORT ═══")
    weekly_report(days=days)


# ── Top-of-funnel pipeline (fully automated) ──────────────────────────────────

def run_top_of_funnel(dry_run: bool = False, yelp_key: str = None, google_key: str = None) -> None:
    """
    Run all automated top-of-funnel steps (prospect → close monitoring).
    Does NOT build or deploy — those require Steele's approval at two gates.

    Order:
    1. Prospect new leads
    2. Score them
    2b. Generate pre-outreach mockups (for scored leads meeting threshold)
    3b. Mail physical postcards via Lob.com (QR code → mockup URL)
    3. Send cold emails (mockup URL is the hook)
    4. Process follow-up sequence
    5. Generate dossiers for booked calls
    6. Monitor inbox for replies
    """
    init_db()
    step_prospect(yelp_key=yelp_key, google_key=google_key)
    step_score()
    step_enrich(dry_run=dry_run)                       # find emails for no-website leads via Facebook
    step_mockup(dry_run=dry_run, pre_outreach=True)   # generate BEFORE sending email
    step_postcard(dry_run=dry_run)                     # mail physical postcards with QR code
    step_outreach(dry_run=dry_run)
    step_followup(dry_run=dry_run)
    step_dossiers()
    step_close(dry_run=dry_run)
    log.info("═══ TOP-OF-FUNNEL COMPLETE ═══")
    log.info(
        "Next: check the CRM for leads in 'agreed_pending' status.\n"
        "For each one, review the intake form and run:\n"
        "  python -m src.orchestrator --step build --lead-id {id}"
    )


run_full_pipeline = run_top_of_funnel  # alias for scheduler.py compat

# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Curbsite AI Sales + Build + Deploy Agent")
    parser.add_argument(
        "--step",
        choices=[
            "prospect", "score", "enrich", "outreach", "postcard", "followup",
            "dossiers", "mockup", "close",
            "build", "approve-build", "domain", "vps-provision", "deploy", "handoff", "golive",
            "reviews", "referrals",
            "report", "all",
        ],
        default="all",
        help="Which step to run (default: all = top-of-funnel only)",
    )
    parser.add_argument(
        "--track",
        choices=["a", "b", "A", "B"],
        default=None,
        help="Deployment track for --step deploy: a=VPS (maintenance plan), b=zip handoff",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending emails or making purchases (safe for testing)",
    )
    parser.add_argument(
        "--yelp-key",
        default=os.getenv("YELP_API_KEY"),
        help="Yelp Fusion API key (optional)",
    )
    parser.add_argument(
        "--google-key",
        default=os.getenv("GOOGLE_MAPS_API_KEY", os.getenv("GOOGLE_PAGESPEED_API_KEY")),
        help="Google Maps/Places API key — requires Places API (New) enabled in GCP",
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
    _lead_required_steps = (
        "build", "approve-build", "domain", "vps-provision",
        "deploy", "handoff", "golive", "dossiers",
    )
    if args.lead_id and args.step not in _lead_required_steps:
        from src.crm.dossier import generate_dossier
        dossier = generate_dossier(args.lead_id)
        print(dossier)
        return

    match args.step:
        case "prospect":
            step_prospect(yelp_key=args.yelp_key, google_key=args.google_key)
        case "score":
            step_score()
        case "enrich":
            step_enrich(dry_run=args.dry_run)
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
        case "postcard":
            step_postcard(dry_run=args.dry_run)
        case "close":
            step_close(dry_run=args.dry_run)
        case "build":
            if not args.lead_id:
                parser.error("--step build requires --lead-id")
            step_build(args.lead_id, dry_run=args.dry_run)
        case "approve-build":
            if not args.lead_id:
                parser.error("--step approve-build requires --lead-id")
            step_approve_build(args.lead_id, dry_run=args.dry_run)
        case "domain":
            if not args.lead_id:
                parser.error("--step domain requires --lead-id")
            step_domain(args.lead_id, preferred_domain=args.domain, dry_run=args.dry_run)
        case "vps-provision":
            if not args.lead_id:
                parser.error("--step vps-provision requires --lead-id")
            step_vps_provision(args.lead_id, dry_run=args.dry_run)
        case "deploy":
            if not args.lead_id:
                parser.error("--step deploy requires --lead-id")
            step_deploy(args.lead_id, track=args.track, dry_run=args.dry_run)
        case "handoff":
            if not args.lead_id:
                parser.error("--step handoff requires --lead-id")
            step_handoff(args.lead_id, dry_run=args.dry_run)
        case "golive":
            if not args.lead_id:
                parser.error("--step golive requires --lead-id")
            step_golive(args.lead_id, dry_run=args.dry_run)
        case "reviews":
            step_reviews(dry_run=args.dry_run)
        case "referrals":
            step_referrals(dry_run=args.dry_run)
        case "report":
            step_report(days=args.days)
        case "all":
            run_top_of_funnel(dry_run=args.dry_run, yelp_key=args.yelp_key, google_key=args.google_key)


if __name__ == "__main__":
    main()
