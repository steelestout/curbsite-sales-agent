# Curbsite Sales Agent 🚀

AI-powered automated sales agent for [Curbsite.co](https://curbsite.co) — a web design agency targeting small businesses. Goal: **3–5 new clients per week** through automated prospecting, scoring, and personalised outreach.

---

## How it works

```
Prospect → Score → Email → Follow-up → (Voice if score ≥ 85 & enabled)
```

1. **Prospect** — Scrapes Yelp Fusion / Google Maps for local businesses by niche + city
2. **Score** — Deterministic scoring (0–100) based on website quality, Google rating, niche value, etc. + optional GPT-4o-mini AI bonus (cached to disk)
3. **Outreach** — Personalised cold emails via SMTP; GPT-4o-mini for most, GPT-4o for top leads
4. **Follow-up** — 2-step automated sequence (Day 3 + Day 7)
5. **Voice** — OpenClaw integration (OFF by default; only fires if `OPENCLAW_ENABLED=true` AND score ≥ 85)

---

## Quick start

```bash
# 1. Clone & set up
git clone https://github.com/YOUR_USERNAME/curbsite-sales-agent
cd curbsite-sales-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY, SMTP credentials, etc.

# 3. Run
python -m src.orchestrator             # full pipeline
python -m src.orchestrator --dry-run   # test without sending emails
python -m src.orchestrator --step prospect   # just find leads
python -m src.orchestrator --step score      # just score new leads
python -m src.orchestrator --step outreach   # just send emails
python -m src.orchestrator --step report     # weekly analytics

# 4. Run continuously (scheduler)
python -m src.scheduler
```

---

## Cost model

| Operation | Model | Est. cost |
|-----------|-------|-----------|
| Score 100 leads | gpt-4o-mini (cached) | ~$0.01 |
| Draft 25 emails | gpt-4o-mini | ~$0.03 |
| Draft 5 top emails | gpt-4o | ~$0.10 |
| **Weekly total** | | **~$0.15–$0.50** |

Disk cache means repeat scoring of the same business costs **$0**.

---

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | required | Your OpenAI key |
| `SMTP_USER` / `SMTP_PASS` | required | Gmail app password recommended |
| `TARGET_CITIES` | `Kokomo` | Comma-separated target cities |
| `TARGET_NICHES` | `restaurant,photography,...` | Business types to target |
| `SCORE_MIN_EMAIL` | `40` | Min score to send initial email |
| `SCORE_VOICE_THRESHOLD` | `85` | Min score for OpenClaw voice call |
| `OPENCLAW_ENABLED` | `false` | **Must be `true` to enable voice calls** |
| `MAX_EMAILS_PER_DAY` | `25` | Daily send cap |

---

## Project structure

```
src/
  config.py           # Central config from .env
  ai_client.py        # OpenAI wrapper (caching + cost tracking)
  orchestrator.py     # Main pipeline runner + CLI
  scheduler.py        # APScheduler cron runner
  prospecting/
    scraper.py        # Yelp + Google Maps lead scraping
    scorer.py         # Lead scoring (deterministic + AI)
  outreach/
    email_composer.py # AI-generated personalised emails
    email_sender.py   # SMTP sending + rate limiting
    openclaw.py       # Voice agent (disabled by default)
  followup/
    sequence.py       # 2-step follow-up automation
  crm/
    database.py       # SQLite: leads, outreach_log, cost_log
  analytics/
    reporter.py       # Weekly report + cost dashboard
tests/
data/
  cache/              # Disk-cached AI responses (gitignored)
  leads/              # SQLite DB (gitignored)
```

---

## OpenClaw (voice calls)

Voice calls are **disabled by default** to keep costs low.

To enable for high-score leads only:
```env
OPENCLAW_ENABLED=true
OPENCLAW_API_KEY=your-key
OPENCLAW_AGENT_ID=your-agent-id
SCORE_VOICE_THRESHOLD=85
```

Calls will only trigger for leads scoring ≥ 85 that haven't been won/lost yet.

---

## Running tests

```bash
pytest tests/ -v
```

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
| **Maximum** | **100** |

---

Built for [Curbsite.co](https://curbsite.co) by Steele Stout.
