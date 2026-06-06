"""
Email composer — generates personalised cold outreach and follow-up emails.

Design principles
─────────────────
1. Every cold email leads with the mockup link — "I already built a preview
   for your site" is the hook that gets opens and clicks.
2. Every email references Curbsite's ballpark pricing so prospects self-qualify.
   No price surprises on the call = more committed bookings.
3. Every email includes the Calendly booking link as a secondary CTA.
4. Keep it short. 5–7 sentences max. No bullet lists. Human tone.
5. gpt-4o-mini for most leads (cheap, fast, cached follow-ups).
   gpt-4o only for leads scored >= 75 (higher quality draft for hot leads).
6. Follow-ups add value (a tip, an example) rather than just nagging.
7. Payment methods in all automated emails: Stripe (via portal), Venmo, or CashApp.
   NEVER mention check or Zelle in automated outreach.

Sequence overview
─────────────────
  Day 0  — Initial cold email: mockup link is the hook, Calendly is the CTA
  Day 3  — Follow-up 1: reference the mockup, add one observation
  Day 7  — Follow-up 2: final touch, low-pressure, leave door open
"""

import json
import logging
import re
from typing import Optional

from src.config import AGENCY_NAME, AGENCY_URL, AGENCY_OWNER, REPLY_TO
from src.ai_client import draft_email
from src.outreach.pricing import recommend_tier, TierRecommendation, PAYMENT_METHODS
from src.outreach.calendly import booking_cta, booking_link

log = logging.getLogger(__name__)

# Common spam trigger words — our AI prompt avoids these, but we log warnings
# if any slip through so we can improve the prompt.
_SPAM_WORDS = {
    "free", "guaranteed", "winner", "click here", "act now", "limited time",
    "special offer", "buy now", "order now", "risk free", "risk-free",
    "100% free", "cash", "prize", "congratulations", "earn money",
    "double your", "million dollars", "no cost", "no credit check",
    "no hidden", "no obligation", "no risk", "obligation free",
    "once in a lifetime", "only $", "per day", "per week",
    "satisfaction guaranteed", "this is not spam", "urgent",
    "you have been selected", "you're a winner",
}

_MAX_SUBJECT_LEN = 50


# ── Content hygiene helpers ───────────────────────────────────────────────────

def _check_spam_words(text: str) -> list[str]:
    """Return any spam trigger words found in the text (lowercased)."""
    lower = text.lower()
    return [w for w in _SPAM_WORDS if w in lower]


def _validate_subject(subject: str) -> str:
    """
    Enforce subject line hygiene: trim to 50 chars, no ALL CAPS,
    no excessive punctuation. Logs a warning if violations are found.
    """
    # Warn on ALL CAPS words (3+ chars)
    if re.search(r'\b[A-Z]{3,}\b', subject):
        log.warning("Subject contains ALL CAPS — may trigger spam filters: %s", subject)

    # Warn on excessive punctuation
    if re.search(r'[!?]{2,}', subject):
        log.warning("Subject has excessive punctuation — may trigger spam filters: %s", subject)

    spam_hits = _check_spam_words(subject)
    if spam_hits:
        log.warning("Subject contains spam trigger words %s: %s", spam_hits, subject)

    if len(subject) > _MAX_SUBJECT_LEN:
        log.warning("Subject is %d chars (max %d): %s", len(subject), _MAX_SUBJECT_LEN, subject)
        subject = subject[:_MAX_SUBJECT_LEN].rstrip()

    return subject


def _check_body(body: str) -> None:
    """Log warnings for spam trigger words found in email body."""
    hits = _check_spam_words(body)
    if hits:
        log.warning(
            "Email body contains %d spam trigger word(s): %s — review before sending.",
            len(hits), hits,
        )


# ── Shared system prompt ───────────────────────────────────────────────────────

def _system_prompt(extra: str = "") -> str:
    return (
        f"You are a friendly, sharp sales copywriter for {AGENCY_NAME} ({AGENCY_URL}), "
        "a web design agency that builds custom sites for small businesses — "
        "restaurants, contractors, photographers, salons, and more.\n\n"
        "Writing rules:\n"
        "- Subject line: under 10 words. Curious, specific, no clickbait. No emojis.\n"
        "- Body: 4–6 sentences max. NO bullet lists. Conversational, warm, direct.\n"
        "- If a mockup URL is provided, reference it prominently — it's the hook, "
        "not an afterthought. Phrase it as 'I already built a free preview' not "
        "'check out this link'.\n"
        "- Mention the ballpark price range naturally — not as a hard sell, "
        "just so the reader knows what world we're in.\n"
        "- End with ONE clear CTA: book the free 15-min call via the provided link.\n"
        f"- Sign off as {AGENCY_OWNER} from {AGENCY_NAME}.\n"
        "- Sound like a real person, not a marketing email.\n"
        "- NEVER use phrases like 'I hope this email finds you well', "
        "'leverage', 'synergy', 'touch base', or 'circle back'.\n"
        "- NEVER use spam trigger words: free, guaranteed, winner, click here, act now, "
        "limited time, special offer, buy now, risk-free, urgent, congratulations.\n"
        "- Subject line: under 50 characters. No ALL CAPS. No !! or ??.\n"
        "- Write plain text only — no HTML, no images, no bullet points with dashes.\n"
        f"- Payment methods, if mentioned: {PAYMENT_METHODS}. "
        "NEVER mention Zelle or check.\n"
        f"{extra}\n"
        "Output format ONLY:\n"
        "SUBJECT: <subject line>\n"
        "BODY:\n<email body>"
    )


# ── Parser ─────────────────────────────────────────────────────────────────────

def _parse_subject_body(raw: str, fallback_subject: str) -> tuple[str, str]:
    """Parse 'SUBJECT: ...\nBODY:\n...' format from AI output."""
    subject = fallback_subject
    body = raw

    if "SUBJECT:" in raw and "BODY:" in raw:
        try:
            s_part, b_part = raw.split("BODY:", 1)
            subject = s_part.replace("SUBJECT:", "").strip().split("\n")[0].strip()
            body = b_part.strip()
        except ValueError:
            pass
    elif "SUBJECT:" in raw:
        lines = raw.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("SUBJECT:"):
                subject = line.replace("SUBJECT:", "").strip()
                body = "\n".join(lines[i + 1:]).strip()
                break

    return subject, body


# ── Initial cold email ─────────────────────────────────────────────────────────

def _get_mockup_url(lead: dict) -> Optional[str]:
    """Pull the mockup URL from the CRM if one has been deployed."""
    try:
        from src.crm.database import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT netlify_url FROM mockups WHERE lead_id=? ORDER BY created_at DESC LIMIT 1",
                (lead["id"],),
            ).fetchone()
        return row["netlify_url"] if row else None
    except Exception:
        return None


def compose_outreach_email(lead: dict) -> tuple[str, str]:
    """
    Generate (subject, body) for the initial cold email to a lead.

    The mockup URL is the primary hook — if one exists, the email leads with
    "I already built a free preview of what your site could look like."
    The Calendly link is the secondary CTA.
    """
    score = lead.get("score", 0)
    high_quality = score >= 75  # gpt-4o for hot leads only

    # Tier recommendation
    rec: TierRecommendation = recommend_tier(lead)

    # Score reasons for context
    score_reasons: list[str] = []
    if lead.get("score_reasons"):
        try:
            score_reasons = json.loads(lead["score_reasons"])
        except (ValueError, TypeError):
            pass

    # Mockup URL — the hook if available
    mockup_url = _get_mockup_url(lead)

    # Build Calendly CTA
    cal_cta = booking_cta(lead, campaign="cold_email")
    cal_link = booking_link(lead, campaign="cold_email")

    # Website situation summary
    wq = lead.get("website_quality", "none")
    if wq == "none":
        web_situation = f"{lead.get('business_name')} doesn't appear to have a website."
    elif wq == "poor":
        web_situation = (
            f"{lead.get('business_name')} has a website, but it looks outdated "
            "and likely isn't showing up well on mobile or in local search."
        )
    else:
        web_situation = (
            f"{lead.get('business_name')} has a decent web presence, "
            "though there's room to grow in local search and conversions."
        )

    owner = lead.get("owner_name")
    greeting = f"Hi {owner}" if owner else "Hi there"

    # Mockup section — the entire pitch changes when we have a mockup
    if mockup_url:
        mockup_instruction = (
            f"IMPORTANT: Lead with the mockup — this is the hook that gets replies.\n"
            f"Start with something like: 'I went ahead and built a free preview of what "
            f"{lead.get('business_name')}'s site could look like — took me about 20 minutes.'\n"
            f"Mockup URL: {mockup_url}\n"
            f"Put the URL prominently in the email (not buried at the end). "
            f"The ask is: 'Take a look and tell me what you think.'\n"
        )
        # When we have a mockup, subjects should reference it
        fallback_subject = f"I built a free preview for {lead.get('business_name', 'your site')}"
    else:
        mockup_instruction = (
            "No mockup available yet. Lead with the observation about their web presence instead.\n"
        )
        fallback_subject = f"Quick question about {lead.get('business_name', 'your business')}"

    user_prompt = (
        f"Write a cold outreach email to the owner of {lead.get('business_name')}, "
        f"a {lead.get('niche')} in {lead.get('city')}, {lead.get('state')}.\n\n"
        f"Greeting: {greeting}\n"
        f"Web situation: {web_situation}\n"
        f"Key insight: {'; '.join(score_reasons[:2]) if score_reasons else 'Strong local reputation with weak online presence.'}\n"
        f"Recommended package: {rec.label} — {rec.email_mention}\n"
        f"Pitch angle: {rec.pitch_angle}\n\n"
        f"{mockup_instruction}\n"
        f"End the email with this booking CTA as the secondary call to action:\n"
        f"{cal_cta}\n\n"
        f"The booking link is: {cal_link}"
    )

    raw = draft_email(_system_prompt(), user_prompt, high_quality=high_quality)
    subject, body = _parse_subject_body(raw, fallback_subject=fallback_subject)

    # Content hygiene checks
    subject = _validate_subject(subject)
    _check_body(body)

    # Guarantee the Calendly link appears in the body even if AI dropped it
    if cal_link not in body and "calendly.com" not in body.lower():
        body += f"\n\n{cal_cta}"

    # Guarantee the mockup link appears if we have one
    if mockup_url and mockup_url not in body:
        body = f"I built a quick free preview of what your site could look like:\n{mockup_url}\n\n" + body

    return subject, body


# ── Follow-up emails ───────────────────────────────────────────────────────────

_FOLLOWUP_CONTEXT = {
    1: (
        "This is follow-up #1, sent 3 days after the initial email. "
        "Keep it to 2–3 sentences. Reference that you emailed before. "
        "Add a small piece of genuine value: mention one specific thing they could improve "
        "(e.g., their Google Business Profile, a missing mobile feature). "
        "End with the booking link — no pressure."
    ),
    2: (
        "This is follow-up #2 — the final touch, sent 7 days after the initial email. "
        "Keep it to 2–3 sentences. Acknowledge this is the last nudge. "
        "Leave the door completely open ('no worries if the timing isn't right'). "
        "Mention that the Calendly link is there whenever they're ready. "
        "End warm, not salesy."
    ),
}


def compose_followup_email(lead: dict, step: int) -> tuple[str, str]:
    """
    Generate (subject, body) for a follow-up email.
    step=1 → Day 3 follow-up
    step=2 → Day 7 final nudge
    """
    context = _FOLLOWUP_CONTEXT.get(step, _FOLLOWUP_CONTEXT[2])
    cal_link = booking_link(lead, campaign=f"followup_{step}")

    user_prompt = (
        f"Write a follow-up email to the owner of {lead.get('business_name')}, "
        f"a {lead.get('niche')} in {lead.get('city')}.\n"
        f"Website quality: {lead.get('website_quality', 'none')}\n"
        f"Context: {context}\n\n"
        f"Booking link (include it): {cal_link}"
    )

    extra = (
        "This is a follow-up. Do NOT restate the full pitch. "
        "Be brief, add one new observation or value point, and include the link."
    )

    raw = draft_email(_system_prompt(extra=extra), user_prompt, high_quality=False)
    subject, body = _parse_subject_body(
        raw,
        fallback_subject=f"Re: {lead.get('business_name', 'your website')}",
    )

    subject = _validate_subject(subject)
    _check_body(body)

    # Guarantee link is present
    if cal_link not in body and "calendly.com" not in body.lower():
        body += f"\n\n{cal_link}"

    return subject, body


# ── LinkedIn / social DM (optional) ───────────────────────────────────────────

def compose_linkedin_dm(lead: dict) -> str:
    """
    Generate a short LinkedIn connection message or DM.
    Max 300 characters (connection note limit).
    """
    rec = recommend_tier(lead)
    cal_link = booking_link(lead, campaign="linkedin")

    system = (
        "Write a LinkedIn connection request note for a web design agency reaching out "
        "to a small business owner. Max 280 characters. Friendly, specific, no buzzwords. "
        "Mention one specific thing about their business. End with a quick call offer. "
        "Output ONLY the message text, nothing else."
    )
    user = (
        f"Target: {lead.get('business_name')}, a {lead.get('niche')} in {lead.get('city')}. "
        f"They {('have no website' if lead.get('website_quality') == 'none' else 'have an outdated website')}. "
        f"Recommended: {rec.label} ({rec.email_mention}). "
        f"Calendly: {cal_link}"
    )

    from src.ai_client import chat
    from src.config import MODEL_DEFAULT
    return chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=MODEL_DEFAULT,
        max_tokens=100,
        temperature=0.5,
        operation="linkedin_dm",
        use_cache=False,
    )
