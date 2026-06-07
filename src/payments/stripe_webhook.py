"""
Payment webhook Flask app — handles both Stripe and Square on port 5001.

Routes:
  POST /webhook/stripe  — Stripe payment_intent.succeeded
  POST /webhook         — backward-compat alias for /webhook/stripe
  POST /webhook/square  — Square payment.completed

Pipeline transitions (both processors):
  50% deposit → status='agreed', auto-build starts
  Final 50%   → status='deployed', go-live triggered

Deploy on Hostinger VPS:
  gunicorn -w 2 -b 0.0.0.0:5001 'src.payments.stripe_webhook:app'

Stripe webhook registration:
  URL: https://curbsite.co/webhook/stripe
  Events: payment_intent.succeeded

Square webhook registration:
  URL: https://curbsite.co/webhook/square
  Events: payment.completed

Portal + Square coordination:
  The curbsite.co portal has its own Square webhook at /api/square/webhook that
  automatically marks invoices Paid when clients pay through the portal checkout.
  This sales-agent webhook (/webhook/square) is responsible ONLY for pipeline state
  transitions (deposit → kick off build, final → trigger go-live). Do not duplicate
  the invoice-marking logic here for Square payments — let the portal handle it.
  For Stripe payments, sync_invoice_to_portal() is still needed since the portal
  has no Stripe webhook of its own.
"""

import logging
import threading
from datetime import datetime

import stripe
from flask import Flask, request, jsonify

from src.config import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    SQUARE_WEBHOOK_SIGNATURE_KEY,
    STEELE_EMAIL,
    PORTAL_URL,
)
from src.crm.database import get_conn, update_lead_status, get_lead
from src.notifications.client_status import (
    notify_build_started,
    notify_client_portal_created,
    notify_payment_confirmed,
    request_steele_approval,
)
from src.payments.square_webhook import verify_square_signature

log = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

app = Flask(__name__)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_lead_by_stripe_pi(pi_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE stripe_deposit_id=? OR stripe_final_id=?",
            (pi_id, pi_id),
        ).fetchone()
    return dict(row) if row else None


def _record_payment_id(
    lead_id: int,
    payment_id: str,
    processor: str,
    is_deposit: bool,
) -> None:
    """Write the payment ID and processor into the lead row."""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        if processor == "stripe":
            field = "stripe_deposit_id" if is_deposit else "stripe_final_id"
            conn.execute(
                f"UPDATE leads SET {field}=?, payment_processor=?, updated_at=? WHERE id=?",
                (payment_id, processor, now, lead_id),
            )
        else:
            conn.execute(
                "UPDATE leads SET square_payment_id=?, payment_processor=?, updated_at=? WHERE id=?",
                (payment_id, processor, now, lead_id),
            )


# ── Shared pipeline handlers ──────────────────────────────────────────────────

def _handle_deposit(
    lead: dict, payment_id: str, processor: str = "stripe", amount_cents: int = 0
) -> None:
    """50% deposit confirmed — move to 'agreed', create portal account, kick off build."""
    lead_id = lead["id"]
    log.info(
        "50%% deposit received — lead #%d (%s) via %s",
        lead_id, lead.get("business_name"), processor,
    )

    _record_payment_id(lead_id, payment_id, processor, is_deposit=True)
    update_lead_status(
        lead_id, "agreed",
        notes=f"50% deposit received via {processor.title()} {payment_id}",
    )

    notify_build_started(lead)

    # Create client portal account and email credentials
    try:
        notify_client_portal_created(lead)
    except Exception as exc:
        log.error("Portal account creation failed for lead #%d: %s", lead_id, exc)

    # Record deposit payment in portal invoice
    try:
        from src.build.portal_sync import sync_invoice_to_portal
        sync_invoice_to_portal(
            lead,
            payment_amount=amount_cents / 100.0,
            processor=processor,
            transaction_id=payment_id,
            is_final=False,
        )
    except Exception as exc:
        log.error("Portal deposit invoice sync failed for lead #%d: %s", lead_id, exc)

    def _do_build():
        try:
            # Set building status and sync to portal before the build runs
            update_lead_status(lead_id, "building", notes="Auto-build started")
            try:
                from src.build.portal_sync import sync_lead_status_to_portal
                sync_lead_status_to_portal(get_lead(lead_id))
            except Exception as exc:
                log.error("Portal building status sync failed for lead #%d: %s", lead_id, exc)

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


def _handle_final(
    lead: dict, payment_id: str, processor: str = "stripe", amount_cents: int = 0
) -> None:
    """Final 50% confirmed — update status, send confirmation, sync portal, trigger go-live."""
    lead_id = lead["id"]
    log.info(
        "Final payment received — lead #%d (%s) via %s",
        lead_id, lead.get("business_name"), processor,
    )

    _record_payment_id(lead_id, payment_id, processor, is_deposit=False)
    update_lead_status(
        lead_id, "deployed",
        notes=f"Final payment received via {processor.title()} {payment_id}",
    )

    lead_fresh = get_lead(lead_id)
    notify_payment_confirmed(lead_fresh)

    # Record final payment in portal invoice and update project status
    try:
        from src.build.portal_sync import sync_invoice_to_portal, sync_lead_status_to_portal
        sync_invoice_to_portal(
            lead_fresh,
            payment_amount=amount_cents / 100.0,
            processor=processor,
            transaction_id=payment_id,
            is_final=True,
        )
        sync_lead_status_to_portal(lead_fresh)  # "Almost live — awaiting final payment"
    except Exception as exc:
        log.error("Portal final-payment sync failed for lead #%d: %s", lead_id, exc)

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


# ── Stripe webhook route ───────────────────────────────────────────────────────

def _stripe_handler():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        log.warning("Invalid Stripe webhook signature — rejecting")
        return jsonify({"error": "bad signature"}), 400
    except Exception as exc:
        log.error("Stripe webhook parse error: %s", exc)
        return jsonify({"error": str(exc)}), 400

    if event["type"] == "payment_intent.succeeded":
        pi = event["data"]["object"]
        pi_id = pi["id"]
        meta = pi.get("metadata", {})

        lead_id_str = meta.get("lead_id")
        payment_type = meta.get("payment_type", "")  # 'deposit' | 'final'

        lead = get_lead(int(lead_id_str)) if lead_id_str else None
        if not lead:
            lead = _get_lead_by_stripe_pi(pi_id)

        if not lead:
            log.warning("PaymentIntent %s has no matching lead — ignoring", pi_id)
            return jsonify({"received": True}), 200

        pi_amount = pi.get("amount", 0)  # Stripe amounts are in cents
        if payment_type == "deposit" or lead.get("stripe_deposit_id") == pi_id:
            _handle_deposit(lead, pi_id, processor="stripe", amount_cents=pi_amount)
        elif payment_type == "final" or lead.get("stripe_final_id") == pi_id:
            _handle_final(lead, pi_id, processor="stripe", amount_cents=pi_amount)
        else:
            log.info("Unclassified Stripe PI %s for lead #%d — no action", pi_id, lead["id"])

    return jsonify({"received": True}), 200


@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    return _stripe_handler()


@app.route("/webhook", methods=["POST"])
def stripe_webhook_legacy():
    """Backward-compatible alias — keeps existing Stripe registration working."""
    return _stripe_handler()


# ── Square webhook route ───────────────────────────────────────────────────────

@app.route("/webhook/square", methods=["POST"])
def square_webhook():
    payload = request.get_data()
    sig = request.headers.get("x-square-hmacsha256-signature", "")

    if not SQUARE_WEBHOOK_SIGNATURE_KEY:
        log.error("SQUARE_WEBHOOK_SIGNATURE_KEY not configured — rejecting")
        return jsonify({"error": "not configured"}), 500

    if not verify_square_signature(payload, sig, SQUARE_WEBHOOK_SIGNATURE_KEY):
        log.warning("Invalid Square webhook signature — rejecting")
        return jsonify({"error": "bad signature"}), 400

    try:
        event = request.get_json(force=True)
    except Exception as exc:
        log.error("Square webhook JSON parse error: %s", exc)
        return jsonify({"error": str(exc)}), 400

    if event.get("type") == "payment.completed":
        payment = event.get("data", {}).get("object", {}).get("payment", {})
        sq_id = payment.get("id", "")
        meta = payment.get("metadata", {})
        amount_cents = payment.get("amount_money", {}).get("amount", 0)

        lead_id_str = meta.get("lead_id")
        payment_type = meta.get("payment_type", "")  # 'deposit' | 'final'

        lead = get_lead(int(lead_id_str)) if lead_id_str else None

        if not lead:
            log.warning("Square payment %s has no matching lead — ignoring", sq_id)
            return jsonify({"received": True}), 200

        # Determine deposit vs final: prefer explicit metadata, fall back to
        # whether we already have a square_payment_id (meaning deposit came first).
        if not payment_type:
            payment_type = "final" if lead.get("square_payment_id") else "deposit"

        log.info(
            "Square %s payment %s — %d cents — lead #%d",
            payment_type, sq_id, amount_cents, lead["id"],
        )

        if payment_type == "deposit":
            _handle_deposit(lead, sq_id, processor="square", amount_cents=amount_cents)
        elif payment_type == "final":
            _handle_final(lead, sq_id, processor="square", amount_cents=amount_cents)
        else:
            log.info("Unclassified Square payment %s for lead #%d — no action", sq_id, lead["id"])

    return jsonify({"received": True}), 200


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("STRIPE_WEBHOOK_PORT", "5001")))
