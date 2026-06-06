"""
⚠️  VOICE CALLING — NOT IMPLEMENTED (intentional decision)

After researching current AI voice agent capabilities (ElevenLabs, Bland.ai,
Vapi, Retell AI), the decision was made to skip automated voice calls
entirely. Here's why:

1. LEGAL RISK (hard blocker as of Jan 27 2026)
   The FCC's One-to-One Consent Rule now requires explicit, per-seller
   prior consent before any AI-assisted or automated call. Cold calling
   scraped leads with an AI voice agent exposes Curbsite to FCC enforcement.
   Source: FCC Report and Order, WC Docket No. 21-402.

2. TRUST DYNAMICS
   Small business owners are relationship-driven and highly skeptical of
   unsolicited calls. A robocall pitching web design — even a convincing one
   — permanently poisons a lead. The downside of a detected AI call outweighs
   any upside. Small business communities are tight-knit; one bad call spreads.

3. WRONG TOOL FOR THE JOB
   Web design sales require nuanced conversation: understanding a specific
   business's history, handling objections like "my nephew handles that" or
   "we tried a website once and it didn't work," and building the personal
   trust that closes a $800–$2,200 contract. This is exactly the kind of
   conversation where human judgment matters.

4. LATENCY / TELL RISK
   Best-in-class platforms (Retell + GPT-4o) achieve ~600ms latency. That's
   good, but longer conversations still have dead air that signals "AI" to
   savvy prospects. In a single one-chance cold call, getting flagged as a
   bot ends the relationship permanently.

THE BETTER MODEL
────────────────
Automate prospecting, scoring, email, and follow-up.
Hand off a pre-qualified lead with a booked Calendly appointment to Steele.
Steele makes the call as a human closer with full context in a dossier.

This is the SalesApe / appointment-setter model — proven to work precisely
because it keeps humans in the closing role.

If voice ever becomes appropriate (inbound call answering, for example),
revisit Retell AI or Vapi at that time. Do not cold-call with AI.
"""

# This file is intentionally a documentation stub.
# Remove it entirely if you want a cleaner repo.

VOICE_ENABLED = False


def trigger_call(*args, **kwargs) -> bool:
    """Voice calling is disabled. See module docstring for rationale."""
    raise NotImplementedError(
        "Voice calling is intentionally not implemented. "
        "See src/outreach/openclaw.py for full explanation."
    )


def is_eligible(*args, **kwargs) -> bool:
    return False
