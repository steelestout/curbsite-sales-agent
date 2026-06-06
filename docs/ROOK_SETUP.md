# Rook Setup Guide
## Connecting the Sales Agent to OpenClaw

---

## Current Status

**Rook is NOT yet deployed.** This guide covers what needs to happen to make
Rook live. The training data and scripts are ready — the agent platform setup
is the remaining step.

No "Rook" code was found on the Hostinger VPS (`187.77.5.53`). Rook will be
a new deployment once the OpenClaw account is set up.

---

## ⚠️ FCC Compliance — Read Before Deploying

**Rook may only make WARM calls.** Under the FCC's One-to-One Consent Rule
(effective January 27, 2026), AI-assisted or automated calls to leads who
have NOT previously engaged with your outreach are prohibited.

**Eligible for Rook calls:**
- Lead opened a Curbsite cold email ✅
- Lead clicked the mockup preview link ✅
- Lead visited curbsite.co from the email ✅
- Lead replied to an email (even just to say not interested) ✅
- Lead filled out any Curbsite form ✅

**NOT eligible for Rook calls:**
- Scraped leads who have never opened or clicked anything ❌
- Leads in 'lost' or 'unsubscribed' status ❌
- Leads with score < 50 ❌

The `get_rook_call_eligibility()` function in `src/rook/sales_training.py`
enforces these rules programmatically.

---

## Step 1 — Get an OpenClaw Account

1. Sign up at [openclaw.ai](https://openclaw.ai) (or the equivalent platform)
2. Create a new AI voice agent named "Rook"
3. Get your API key and Agent ID
4. Add to `.env`:

```env
OPENCLAW_API_KEY=your_api_key_here
OPENCLAW_AGENT_ID=your_agent_id_here
OPENCLAW_API_BASE=https://api.openclaw.ai/v1
```

---

## Step 2 — Assemble and Upload Rook's Training Prompt

The training data lives in `data/rook/`. The Python module assembles it
into a single system prompt and uploads it to OpenClaw.

**Preview the assembled prompt:**
```bash
python -m src.rook.sales_training --dry-run
```

**Validate it (check for required content and forbidden phrases):**
```bash
python -m src.rook.sales_training --validate
```

**Upload to OpenClaw:**
```bash
python -m src.rook.sales_training --upload
```

**Upload with a specific agent ID (overrides .env):**
```bash
python -m src.rook.sales_training --upload --agent-id abc123
```

---

## Step 3 — Configure Rook's Voice and Behavior in OpenClaw

In the OpenClaw dashboard:

1. **Voice**: Choose a warm, natural male voice. Avoid robotic-sounding TTS.
   Recommended: ElevenLabs "Adam" or "Josh" if OpenClaw supports custom voices.

2. **First message** (what Rook says when the call connects):
   > "Hey, is this [prospect_name]? This is Rook from Curbsite —
   > I sent you an email about [business_name]'s website. Got 60 seconds?"

   Configure `prospect_name` and `business_name` as dynamic variables
   passed from the CRM when triggering the call.

3. **Interruption handling**: Set to "allow interruptions" — natural conversation,
   not a one-way script.

4. **End call triggers**: Rook should end the call when the prospect says:
   - "No thanks"
   - "Not interested"
   - "Please don't call again"
   - Any clear goodbye

5. **Post-call webhook**: Configure a webhook to POST call outcomes back to
   the sales agent pipeline. The webhook should hit:
   `POST https://[your-server]/api/rook/call-outcome`
   with JSON: `{ "lead_id": int, "outcome": "positive|negative|question", "notes": str }`

---

## Step 4 — Triggering Calls from the Pipeline

Add to `.env`:
```env
OPENCLAW_API_KEY=...
OPENCLAW_AGENT_ID=...
```

The orchestrator will trigger Rook calls for eligible leads:
```bash
python -m src.orchestrator --step rook-calls --dry-run
```

Or manually for a specific lead:
```bash
python -m src.orchestrator --step rook-calls --lead-id 42
```

---

## Step 5 — Training Data Structure

All training files are in `data/rook/`:

```
data/rook/
├── training_prompt.md          ← Main character brief + full pricing
└── sales_scripts/
    ├── cold_call.md            ← Script for calling post-email-open leads
    ├── warm_followup.md        ← Script for calling post-mockup-click leads
    ├── objection_handling.md   ← Response library for common pushbacks
    └── closing.md              ← Closing tracks A/B/C + payment close
```

**To update training data:**
1. Edit the relevant `.md` files
2. Run `python -m src.rook.sales_training --validate`
3. Run `python -m src.rook.sales_training --upload`

---

## Step 6 — Testing Before Going Live

1. Call yourself first. Listen to how Rook sounds.
2. Run through each objection in `objection_handling.md` manually.
3. Confirm the mockup link and Calendly link are being passed correctly.
4. Test the CRM webhook — verify call outcomes update lead status.
5. Test the eligibility gate — attempt to trigger a call for an ineligible
   lead and confirm it's blocked.

---

## VPS Deployment (if Rook needs a dedicated server)

Rook itself runs on the OpenClaw platform (cloud) — no VPS needed for Rook.

The sales agent pipeline (prospecting, email, mockup) runs on your local
machine or the existing Hostinger VPS at `187.77.5.53`.

If you need to run the orchestrator on the VPS (for 24/7 operation):

```bash
# On the VPS: /opt/curbsite-sales-agent/
git clone https://github.com/steelestout/curbsite-sales-agent.git
cd curbsite-sales-agent
pip install -r requirements.txt
cp .env.example .env  # fill in credentials
# Run via cron or supervisor
python -m src.orchestrator
```

---

## Notes on the Existing `openclaw.py` File

`src/outreach/openclaw.py` documents the original decision NOT to do AI
cold calling due to FCC compliance. That rationale still applies.

Rook is different because it makes **warm calls only** — to leads who've
already opened an email or visited the mockup. That interaction constitutes
prior engagement, putting it in a different legal category from cold AI calls.

If you're ever unsure whether a lead is eligible, run:
```python
from src.rook.sales_training import get_rook_call_eligibility
eligible, reason = get_rook_call_eligibility(lead)
print(eligible, reason)
```
