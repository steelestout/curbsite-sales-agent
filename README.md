# Curbsite Sales Agent 🚀

AI-powered appointment-booking pipeline for [Curbsite.co](https://curbsite.co).

**Goal:** Generate 3–5 qualified, booked sales calls per week — fully automated up to the call. Steele closes.

---

## Philosophy

> Automate everything up to the call. Hand off to a human with full context.

This is the appointment-setter model: the agent finds leads, qualifies them, sends personalised outreach with ballpark pricing, runs a follow-up sequence, and books a Calendly slot. When a prospect books, Steele gets a **pre-call dossier** — business snapshot, score reasoning, recommended package, conversation starters, and likely objections — so he can walk in prepared and close.

**Why no AI voice calls?** Two hard blockers:
1. **FCC (Jan 2026)** — The One-to-One Consent Rule requires explicit per-seller consent before any AI-assisted cold call. Cold-calling scraped leads = legal exposure.
2. **Trust** — Small business owners are relationship-driven. A robocall pitching web design permanently poisons a lead. The downside of detection is asymmetric. See `src/outreach/openclaw.py` for the full rationale.

---

## Pipeline

```
Prospect → Score → Email (w/ Calendly link + pricing) → Follow-up × 2 → Dossier
```

| Step | What happens |
|------|-------------|
| **1. Prospect** | Scrapes Yelp Fusion + Google Maps for local businesses by niche + city |
| **2. Score** | 0–100 score: website quality, Google rating, niche value, review count + GPT-4o-mini AI bonus (disk-cached) |
| **3. Outreach** | Personalised cold email with Calendly booking link + ballpark pricing. GPT-4o-mini for most leads, GPT-4o for score ≥ 75 |
| **4. Follow-up** | Day 3: quick observation + value tip. Day 7: low-pressure final touch. Both include Calendly link |
| **5. Dossier** | When a lead books → auto-generate pre-call brief saved to `data/leads/dossiers/` |

---

## Quick start

```bash
# 1. Clone & install
git clone https://github.com/steelestout/curbsite-sales-agent
cd curbsite-sales-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Required: OPENAI_API_KEY, SMTP_USER, SMTP_PASS, CALENDLY_URL

# 3. Run (dry-run first — no emails sent)
python -m src.orchestrator --dry-run

# 4. Run for real
python -m src.orchestrator

# 5. Run on autopilot (APScheduler cron)
python -m src.scheduler
```

---

## Key commands

```bash
# Individual steps
python -m src.orchestrator --step prospect    # find new leads
python -m src.orchestrator --step score       # score unscored leads
python -m src.orchestrator --step outreach    # send initial emails
python -m src.orchestrator --step followup    # send due follow-ups
python -m src.orchestrator --step dossiers    # generate dossiers for booked leads
python -m src.orchestrator --step report      # weekly analytics + cost report

# Generate a dossier for a specific lead (by DB id)
python -m src.orchestrator --lead-id 42

# Run tests
pytest tests/ -v
```

---

## Calendly setup

1. Create a **"15-minute intro call"** event type on [Calendly](https://calendly.com)
2. Copy the direct URL (e.g. `https://calendly.com/steele-curbsite/15min`)
3. Set `CALENDLY_URL=<your link>` in `.env`

The agent appends UTM parameters (`utm_source`, `utm_medium`, `utm_content=lead_id-slug`) to every link so you can see in Calendly which lead booked.

**Optional:** Set `CALENDLY_WEBHOOK_SECRET` to receive booking notifications and auto-update lead status to `call_scheduled`.

---

## Pricing tiers (Curbsite.co)

Referenced in every cold email and in the pre-call dossier so prospects self-qualify before the call:

| Tier | Starting price | Best for |
|------|---------------|---------|
| **Entry** | $800 | Photographers, small shops, new businesses — 4-page site |
| **Mid** | $1,400 | Restaurants, salons, gyms — gallery, booking link, schema |
| **Top** | $2,200 | Contractors, dental, roofing — advanced SEO, landing page, 30-day support |
| **Care Plan** | $75–125/month | Any tier — hosting, maintenance, updates |

All prices configurable via `.env` (`PRICE_ENTRY`, `PRICE_MID`, `PRICE_TOP`, etc.).

---

## Cost model

| Operation | Model | Est. weekly cost |
|-----------|-------|-----------------|
| Score 200 leads | gpt-4o-mini (disk-cached) | ~$0.02 |
| Draft 25 cold emails | gpt-4o-mini | ~$0.04 |
| Draft 5 top emails | gpt-4o | ~$0.12 |
| Generate 5 dossiers | gpt-4o-mini (cached) | ~$0.02 |
| Follow-up emails | gpt-4o-mini | ~$0.03 |
| **Weekly total** | | **~$0.20–$0.50** |

Disk cache means scoring the same business twice costs **$0**.

---

## Scoring breakdown

| Signal | Points |
|--------|--------|
| No website | +30 |
| Poor website | +15 |
| Okay website | +5 |
| Google rating 3.5–4.4 | +10 |
| Rating > 4.4 | +5 |
| Review count < 50 | +5 |
| Review count ≥ 50 | +10 |
| High-value niche (restaurant/dental/contractor) | +10 |
| Medium-value niche (salon/fitness/photography) | +5 |
| Has phone number | +5 |
| AI bonus (gpt-4o-mini, cached) | 0–10 |
| **Max** | **100** |

Leads scoring ≥ `SCORE_MIN_EMAIL` (default 40) get an initial email.

---

## Scheduler (autopilot)

```bash
python -m src.scheduler
```

| Schedule | Job |
|----------|-----|
| Mon–Fri 8:00 AM | Full pipeline (prospect + score + outreach) |
| Daily 9:00 AM | Process due follow-ups |
| Monday 7:00 AM | Weekly analytics report |
| Daily midnight | Reset email counter |

Timezone: `America/Indiana/Indianapolis` (configurable in `src/scheduler.py`)

---

## Project structure

```
src/
  config.py              # Central config from .env
  ai_client.py           # OpenAI wrapper (disk cache + cost tracking + retry)
  orchestrator.py        # CLI pipeline runner
  scheduler.py           # APScheduler cron runner
  prospecting/
    scraper.py           # Yelp Fusion + Google Maps lead scraping
    scorer.py            # Lead scoring (deterministic + AI bonus, cached)
  outreach/
    email_composer.py    # AI-generated emails with Calendly link + pricing
    email_sender.py      # SMTP sending with daily rate limit
    pricing.py           # Tier recommendation + pricing reference
    calendly.py          # Booking link generation + webhook parsing
    openclaw.py          # Voice stub — disabled (see file for rationale)
  followup/
    sequence.py          # 2-step follow-up automation
  crm/
    database.py          # SQLite: leads, outreach_log, followup_queue, cost_log
    dossier.py           # Pre-call brief generator (markdown)
  analytics/
    reporter.py          # Weekly pipeline + cost report
tests/
data/
  cache/                 # Disk-cached AI responses (gitignored)
  leads/                 # SQLite DB + dossiers (gitignored)
```

---

Built for [Curbsite.co](https://curbsite.co) by Steele Stout.
