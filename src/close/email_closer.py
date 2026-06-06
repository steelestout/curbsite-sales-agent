"""
Email closer — monitors the inbox for prospect replies and classifies them.

Flow
────
1. Connect to IMAP inbox (same address as SMTP_USER)
2. Find emails in the INBOX from known prospect addresses
3. GPT-4o-mini classifies each reply as: positive | negative | neutral | question
4. Positive → update lead to 'agreed', log for Steele's Gate 1 review
5. Negative → update lead to 'lost'
6. Question/neutral → flag 'review_needed' in CRM, do nothing else

Close rules (agent can auto-close via email)
────────────────────────────────────────────
- Reply is positive AND
- Lead status was 'mockup_sent' (they saw the mockup) AND
- Lead score >= 50 AND
- Reply contains no questions (classifier says no open_question)
- → status set to 'agreed_pending' and Steele gets a notification

Status after classification
───────────────────────────
  positive (all rules met) → agreed_pending (Steele must confirm at Gate 1)
  positive (rules not met) → agreed_pending + review_needed flag
  negative                 → lost
  question/neutral         → review_needed flag only (status unchanged)
"""

import email
import imaplib
import logging
import os
import re
from datetime import datetime
from email.header import decode_header
from typing import Optional

from src.config import (
    SMTP_USER, SMTP_PASS, FROM_EMAIL,
    AGENCY_NAME, AGENCY_OWNER,
    MODEL_DEFAULT,
)
from src.ai_client import chat
from src.crm.database import get_leads, get_lead, update_lead_status, get_conn, log_outreach

log = logging.getLogger(__name__)

_IMAP_HOST: str = os.getenv("IMAP_HOST", "imap.gmail.com")
_IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))
_SCORE_THRESHOLD_AUTO_CLOSE: int = 50

# ── Reply classifier ──────────────────────────────────────────────────────────

_CLASSIFY_SYSTEM = """\
You classify email replies from small business owners to a web agency cold outreach.
A web design agency contacted them; they may have received a free website mockup.

Classify the reply as EXACTLY ONE of:
  positive  — owner is interested, wants to proceed, or says yes
  negative  — owner declines, not interested, or says no
  question  — owner asks something (price, timeline, process, etc.)
  neutral   — noncommittal, polite acknowledgment, or unclear

Also determine if the reply contains an open question that needs a human answer.

Output ONLY valid JSON:
{
  "classification": "positive|negative|question|neutral",
  "open_question": true|false,
  "confidence": 0-100,
  "summary": "1-sentence summary of what they said"
}"""


def classify_reply(reply_text: str) -> dict:
    """Classify a prospect's email reply. Returns a dict with classification info."""
    user = f"Email reply text:\n\n{reply_text[:1500]}"

    raw = chat(
        messages=[
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=MODEL_DEFAULT,
        max_tokens=120,
        temperature=0.1,
        operation="reply_classify",
        use_cache=False,
    )

    try:
        import json
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        result = json.loads(clean)
        return result
    except (ValueError, KeyError):
        log.warning("Failed to parse reply classification: %s", raw[:100])
        # Conservative fallback: treat as neutral so Steele reviews it
        return {
            "classification": "neutral",
            "open_question": True,
            "confidence": 0,
            "summary": "Parse error — manual review required",
        }


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def _decode_header_value(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _get_email_body(msg: email.message.Message) -> str:
    """Extract plain text body from an email.message.Message object."""
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    body_parts.append(
                        part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                    )
                except Exception:
                    pass
    else:
        try:
            body_parts.append(
                msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                )
            )
        except Exception:
            pass
    return "\n".join(body_parts)


def _fetch_replies(prospect_emails: set[str]) -> list[dict]:
    """
    Connect to IMAP and fetch unread emails from any address in prospect_emails.
    Returns a list of dicts with keys: from_email, subject, body, uid.
    """
    if not prospect_emails:
        return []

    try:
        mail = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
        mail.login(SMTP_USER, SMTP_PASS)
        mail.select("INBOX")
    except imaplib.IMAP4.error as exc:
        log.error("IMAP login failed: %s", exc)
        return []

    replies = []
    for prospect_email in prospect_emails:
        try:
            status, data = mail.search(None, f'(UNSEEN FROM "{prospect_email}")')
            if status != "OK" or not data[0]:
                continue
            uids = data[0].split()
            for uid in uids:
                status, msg_data = mail.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                replies.append({
                    "from_email": prospect_email,
                    "subject": _decode_header_value(msg.get("Subject", "")),
                    "body": _get_email_body(msg),
                    "uid": uid.decode(),
                })
        except Exception as exc:
            log.warning("Error fetching replies from %s: %s", prospect_email, exc)

    try:
        mail.logout()
    except Exception:
        pass

    return replies


# ── Status transitions ────────────────────────────────────────────────────────

def _handle_positive(lead: dict, classification: dict, reply_body: str) -> None:
    lead_id = lead["id"]
    lead_score = lead.get("score", 0)
    lead_status = lead.get("status", "")

    saw_mockup = lead_status == "mockup_sent"
    above_threshold = lead_score >= _SCORE_THRESHOLD_AUTO_CLOSE
    no_open_question = not classification.get("open_question", True)
    auto_close_ok = saw_mockup and above_threshold and no_open_question

    notes = (
        f"POSITIVE REPLY [{classification.get('confidence', 0)}% confidence]: "
        f"{classification.get('summary', '')} | "
        f"auto_close_ok={auto_close_ok} | "
        f"reply_preview={reply_body[:200]}"
    )

    update_lead_status(lead_id, "agreed_pending", notes=notes)
    log.info(
        "Lead #%d %s → agreed_pending (auto_close=%s)",
        lead_id, lead.get("business_name"), auto_close_ok,
    )

    if not auto_close_ok:
        _flag_for_review(lead_id, reason="positive reply but auto-close conditions not met")

    # Notify Steele
    _notify_steele_positive(lead, classification, auto_close_ok)


def _handle_negative(lead: dict, classification: dict) -> None:
    lead_id = lead["id"]
    notes = (
        f"NEGATIVE REPLY: {classification.get('summary', '')} "
        f"[{classification.get('confidence', 0)}% confidence]"
    )
    update_lead_status(lead_id, "lost", notes=notes)
    log.info("Lead #%d %s → lost", lead_id, lead.get("business_name"))


def _handle_question(lead: dict, classification: dict, reply_body: str) -> None:
    lead_id = lead["id"]
    _flag_for_review(lead_id, reason=classification.get("summary", "open question"))
    log.info(
        "Lead #%d %s → review_needed (question/neutral: %s)",
        lead_id, lead.get("business_name"), classification.get("summary", ""),
    )


def _flag_for_review(lead_id: int, reason: str) -> None:
    """Set a review_needed flag in the outreach log."""
    log_outreach(
        lead_id=lead_id,
        type_="review_flag",
        subject="REVIEW NEEDED",
        body=reason,
    )


def _notify_steele_positive(lead: dict, classification: dict, auto_close_ok: bool) -> None:
    """
    Log a prominent notification. In a full system this would push to Slack/SMS.
    For now it's a clear log entry — Steele will see it in the daily report.
    """
    icon = "🟢" if auto_close_ok else "🟡"
    log.info(
        "%s POSITIVE REPLY — %s (%s)\n"
        "   Summary: %s\n"
        "   Score: %d | Auto-close OK: %s\n"
        "   Action: Confirm at curbsite.co/portal → lead #%d",
        icon,
        lead.get("business_name"),
        lead.get("email"),
        classification.get("summary", ""),
        lead.get("score", 0),
        auto_close_ok,
        lead["id"],
    )


# ── Public API ────────────────────────────────────────────────────────────────

def process_replies(dry_run: bool = False) -> dict:
    """
    Check the inbox for replies from known prospects and process each one.

    Returns stats dict: {checked, positive, negative, question, neutral, errors}
    """
    # Get all leads that have been emailed or sent a mockup
    emailed_leads = get_leads(status="emailed", limit=500)
    followed_leads = get_leads(status="followed_up", limit=500)
    mockup_leads = get_leads(status="mockup_sent", limit=500)

    all_leads = {
        lead["email"]: lead
        for lead in (emailed_leads + followed_leads + mockup_leads)
        if lead.get("email")
    }

    if not all_leads:
        log.info("No emailed leads to check for replies.")
        return {"checked": 0, "positive": 0, "negative": 0, "question": 0, "neutral": 0, "errors": 0}

    log.info("Checking inbox for replies from %d prospects...", len(all_leads))
    replies = _fetch_replies(set(all_leads.keys()))
    log.info("Found %d unread replies", len(replies))

    stats = {"checked": len(replies), "positive": 0, "negative": 0, "question": 0, "neutral": 0, "errors": 0}

    for reply in replies:
        from_email = reply["from_email"]
        lead = all_leads.get(from_email)
        if not lead:
            log.debug("No lead found for reply from %s — skipping", from_email)
            continue

        try:
            classification = classify_reply(reply["body"])
            cls = classification.get("classification", "neutral")

            log.info(
                "Reply from %s [%s]: %s → %s",
                lead.get("business_name"),
                from_email,
                cls,
                classification.get("summary", ""),
            )

            if not dry_run:
                if cls == "positive":
                    _handle_positive(lead, classification, reply["body"])
                    stats["positive"] += 1
                elif cls == "negative":
                    _handle_negative(lead, classification)
                    stats["negative"] += 1
                elif cls == "question":
                    _handle_question(lead, classification, reply["body"])
                    stats["question"] += 1
                else:
                    _handle_question(lead, classification, reply["body"])
                    stats["neutral"] += 1
            else:
                log.info("[DRY RUN] Would classify reply as: %s", cls)
                stats[cls if cls in stats else "neutral"] += 1

        except Exception as exc:
            log.error("Error processing reply from %s: %s", from_email, exc)
            stats["errors"] += 1

    return stats
