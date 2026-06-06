"""
Stripe webhook handler — Flask app for payment events.

Events handled:
  payment_intent.succeeded
    payment_type=deposit  → status 'agreed', trigger build, notify Steele
    payment_type=final    → trigger deploy/golive

Deploy on Hostinger VPS:
  gunicorn -w 2 -b 0.0.0.0:5001 'src.payments.stripe_webhook:app'

Register at https://dashboard.stripe.com/webhooks:
  Endpoint: https://curbsite.co/stripe/webhook
  Events:   payment_intent.succeeded

See docs/STRIPE_SETUP.md for full setup instructions.
"""

import logging
import threading
from datetime import datetime

import stripe
from flask import Flask, request, jsonify

from src.config import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    STEELE_EMAIL,
    PORTAL_URL,
)
from src.crm.database import get_conn, update_lead_status, get_lead
from src.notifications.client_status import (
    notify_build_started,
    notify_payment_confirmed,
    request_steele_approval,
)

log = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

app = Flask(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_lead_by_pi(pi_id: str) -> dict | None:
    """Find a lead that references this PaymentIntent ID."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE stripe_deposit_id=? OR stripe_final_id=?",
            (pi_id, pi_id),
        ).fetchone()
    return dict(row) if row else None


def _set_stripe_pi(lead_id: int, field: str, pi_id: str) -> None:
    """Store a Stripe PaymentIntent ID on the lead row."""
    with get_conn() as conn:
        conn.execute(
            f"UPDATE leads SET {field}=?, updated_at=? WHERE id=?",
            (pi_id, datetime.utcnow().isoformat(), lead_id),
        )


# ── Payment handlers ──────────────────────────────────────────────────────────

def _handle_deposit(lead: dict, pi_id: str) -> None:
    """50% deposit confirmed — move to 'agreed', kick off build."""
    lead_id = lead["id"]
    log.info("50%% deposit received — lead #%d (%s)", lead_id, lead.get("business_name"))

    _set_stripe_pi(lead_id, "stripe_deposit_id", pi_id)
    update_lead_status(
        lead_id, "agreed",
        notes=f"50% deposit received via Stripe PI {pi_id}",
    )

    notify_build_started(lead)

    def _do_build():
        try:
            from src.build.site_builder import build_site
            build_site(lead)
            request_steele_approval(lead_id)
        except Exception as exc:
            log.error("Auto-build failed for lead #%d: %s", lead_id, exc)
            from src.notifications.client_status import _send_steele
            _send_steele(
                subject=f"[Curbsite] ⚠ Build FAILED — {lead['business_name']}",
                text=(
                    f"The auto-build for lead #{lead_id} ({lead['business_name']}) "
                    f"failed with error:\n\n{exc}\n\n"
                    f"Run manually: python -m src.orchestrator --step build --lead-id {lead_id}"
                ),
            )

    threading.Thread(target=_do_build, daemon=True).start()


def _handle_final(lead: dict, pi_id: str) -> None:
    """Final 50% confirmed — update status, send confirmation, trigger golive."""
    lead_id = lead["id"]
    log.info("Final payment received — lead #%d (%s)", lead_id, lead.get("business_name"))

    _set_stripe_pi(lead_id, "stripe_final_id", pi_id)
    update_lead_status(
        lead_id, "deployed",
        notes=f"Final payment received via Stripe PI {pi_id}",
    )

    lead_fresh = get_lead(lead_id)
    notify_payment_confirmed(lead_fresh)

    def _do_golive():
        try:
            from src.deploy.golive import run_golive
            domain = lead_fresh.get("domain")
            if domain:
                run_golive(lead_fresh, domain, portal_url=PORTAL_URL)
            else:
                log.warning("No domain for lead #%d — skipping auto-golive", lead_id)
        except Exception as exc:
            log.error("Auto-golive failed for lead #%d: %s", lead_id, exc)

    threading.Thread(target=_do_golive, daemon=True).start()


# ── Webhook route ─────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        log.warning("Invalid Stripe webhook signature — rejecting")
        return jsonify({"error": "bad signature"}), 400
    except Exception as exc:
        log.error("Webhook parse error: %s", exc)
        return jsonify({"error": str(exc)}), 400

    if event["type"] == "payment_intent.succeeded":
        pi = event["data"]["object"]
        pi_id = pi["id"]
        meta = pi.get("metadata", {})

        lead_id_str = meta.get("lead_id")
        payment_type = meta.get("payment_type", "")  # 'deposit' | 'final'

        lead = get_lead(int(lead_id_str)) if lead_id_str else None
        if not lead:
            lead = _get_lead_by_pi(pi_id)

        if not lead:
            log.warning("PaymentIntent %s has no matching lead — ignoring", pi_id)
            return jsonify({"received": True}), 200

        if payment_type == "deposit" or lead.get("stripe_deposit_id") == pi_id:
            _handle_deposit(lead, pi_id)
        elif payment_type == "final" or lead.get("stripe_final_id") == pi_id:
            _handle_final(lead, pi_id)
        else:
            log.info("Unclassified PI %s for lead #%d — no action", pi_id, lead["id"])

    return jsonify({"received": True}), 200


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("STRIPE_WEBHOOK_PORT", "5001")))
