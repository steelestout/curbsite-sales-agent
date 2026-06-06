# Curbsite.co — Full Sales Process

This document is the agent's canonical reference for how the Curbsite.co business works,
end-to-end, from cold prospect to live client website. Every pipeline step maps directly
to a module in `src/`.

---

## Pricing Tiers (from `.env`)

| Tier    | Price  | Pages                                      | Key Features                                              |
|---------|--------|--------------------------------------------|-----------------------------------------------------------|
| Entry   | $800   | Home, Services, About, Contact             | Mobile-first, click-to-call, Maps, GA4, SSL, contact form |
| Mid     | $1,400 | + Gallery, Reviews, Industry page          | + Booking link, email capture, LocalBusiness schema, SEO  |
| Top     | $2,200 | + Events, Staff, Landing page              | + Advanced local SEO, gift cards, 2 revisions, 30-day support |
| Care    | $75–125/mo | — | Ongoing hosting, maintenance, content updates (cancel anytime) |

Tier is recommended automatically based on niche, review count, and website quality.
Steele may override the recommendation on any call.

---

## Tech Stack (every client site)

- **Framework**: Next.js 14 (App Router) + Tailwind CSS
- **DB**: SQLite (Prisma) → Postgres at scale
- **Auth**: NextAuth.js (client portal)
- **Deployment**: Docker → Hostinger VPS + Traefik (HTTPS auto via Let's Encrypt)
- **Email**: Namecheap Private Email via Nodemailer
- **Analytics**: Google Analytics 4 (one property per client)
- **Payments**: Square (production) / Stripe (invoicing via portal)
- **Mockup previews**: Static HTML + Tailwind CDN deployed to Netlify free tier

---

## The Pipeline: 9 States

Each lead moves through these states in `leads.status`:

```
new → scored → emailed → followed_up → mockup_sent → agreed → building → domain_purchased → deployed → live
                                                                         ↘ lost / unsubscribed (any stage)
```

---

## Stage-by-Stage Breakdown

### Stage 1: Prospect → `new`
**Module**: `src/prospecting/scraper.py`

- Scrapes Yelp (API) and Google Maps for local businesses
- Target cities: Kokomo, Indianapolis, Fort Wayne (configurable via `TARGET_CITIES`)
- Target niches: restaurant, photography, salon, contractor, fitness, dental
- Stored in SQLite CRM with business name, city, niche, phone, website, reviews

### Stage 2: Score → `scored`
**Module**: `src/prospecting/scorer.py`

- GPT-4o-mini scores each lead 0–100
- Factors: no/poor website, review count, niche fit, Google rating
- Only leads scoring ≥ 40 (`SCORE_MIN_EMAIL`) get emailed

### Stage 3: Outreach → `emailed`
**Module**: `src/outreach/email_composer.py`, `src/outreach/email_sender.py`

- Personalized cold email with:
  - Specific observation about their web presence
  - Tier recommendation + ballpark price
  - Calendly booking link (15-min call)
- GPT-4o-mini for most leads; GPT-4o for score ≥ 75
- Max 25 emails/day (safety rail)

### Stage 4: Follow-up → `followed_up`
**Module**: `src/followup/sequence.py`

- Day 3: Follow-up 1 — quick observation + value tip
- Day 7: Follow-up 2 — final nudge, leave door open
- Both include Calendly link

### Stage 5: Free Mockup → `mockup_sent`
**Module**: `src/mockup/generator.py`, `src/mockup/delivery.py`

This is the hook. Before the prospect has paid anything, they receive a link to a
real, working mockup of their website — built in ~5 minutes using their business info.

**Generator** (`generator.py`):
- Pulls business name, niche, city, phone, address, and any scraped info from CRM
- GPT-4o-mini generates all copy: tagline, hero text, services (×3), about blurb, CTA
- Niche-specific color palette applied automatically
- Outputs a single `index.html` using Tailwind CDN — no build step
- Saved to `data/mockups/{lead_id}/index.html`
- Copy is cached by niche to minimize tokens

**Delivery** (`delivery.py`):
- Deploys HTML to Netlify free tier via Deploy API
- Each lead gets a unique subdomain: `{slug}.netlify.app`
- Sends prospect a "Here's a free mockup of your new website" email
- Updates lead status to `mockup_sent`

**Trigger**: Automatically after a Calendly booking is confirmed OR manually via
`python -m src.orchestrator --step mockup --lead-id {id}`

### Stage 6: Close → `agreed`
**Module**: `src/close/email_closer.py`

- Monitors SMTP inbox (IMAP) for replies from prospects
- GPT-4o-mini classifies replies: `positive` / `negative` / `neutral` / `question`
- **Positive reply** → status becomes `agreed`, triggers build pipeline
- **Negative reply** → status becomes `lost`
- **Question/neutral** → flagged in CRM for Steele to handle manually
- Runs on a cron / manual trigger

**Can the agent close via email without a phone call?**
Yes, under these conditions:
1. Prospect explicitly says "yes", "let's do it", "I'm interested", or similar
2. Lead score ≥ 50
3. No open questions about price, timeline, or scope

If any question is unresolved, the agent flags it and waits for Steele.

### Stage 7: Full Build → `building`
**Module**: `src/build/site_builder.py`

**Trigger**: Lead status becomes `agreed`

**Input sources (in priority order)**:
1. CRM lead record (scraped business info)
2. Client intake form responses (submitted via curbsite.co/portal — **TODO: Steele to
   clarify exact portal integration**)
3. Photos/files uploaded to portal Projects tab

**Build process**:
- Assembles the brand layer from intake data: colors, fonts, logo, photos
- GPT-4o polishes all final copy (tagline, hero, services, about, CTAs)
- Generates a complete Next.js 14 site from template in `data/builds/{lead_id}/`
- Creates `docker-compose.yml` and `Dockerfile` for deployment
- For Entry tier: 4 static pages; Mid: +gallery/menu; Top: +events/landing
- Outputs a ready-to-deploy package

**Minimum requirements to build** (from intake checklist):
- Business name, phone, email, address, hours
- Logo (or confirmed text-only wordmark)
- At least 5 usable photos
- Services list
- 50% deposit received (verified via Square/Stripe webhook in portal)

### Stage 8: Domain Purchase → `domain_purchased`
**Module**: `src/deploy/domain.py`

- Checks availability via Namecheap API
- Purchases domain (≈$10–15/yr)
- Falls back to GoDaddy API if Namecheap unavailable
- Logs purchase details to `domains` table
- Returns registered domain name

### Stage 9: Deploy → `deployed` → `live`
**Modules**: `src/deploy/host.py`, `src/deploy/golive.py`

**host.py**:
- SSH into Hostinger VPS (paramiko)
- Creates `/var/www/{domain}/` directory
- Uploads built site via SFTP
- Writes `docker-compose.yml` with Traefik labels for domain + SSL
- Runs `docker-compose up -d`
- Traefik auto-provisions Let's Encrypt SSL
- Updates DNS at Namecheap to point domain → VPS IP

**golive.py**:
- Polls HTTPS endpoint every 30s for up to 10 minutes
- On first 200 response: status → `live`
- Sends client "Your site is live!" email with:
  - Live URL
  - Portal login link (curbsite.co/portal)
  - Next steps (review, Google Business Profile, care plan)
- Logs go-live timestamp

---

## The Owner Portal

**URL**: `curbsite.co/portal`  
**Tech**: Part of the main Curbsite Next.js app on Hostinger VPS

Clients register at `curbsite.co/portal/register` after the 50% deposit.  
Portal features (all tiers):
- Dashboard: balance, project status, messages
- Projects: upload files, leave feedback, track build progress
- Invoices: view + pay via Square
- Messages: direct thread with Curbsite team

**Agent integration TODO**: The pipeline currently reads uploaded files by path
(`PORTAL_FILE_BASE_PATH` env var). Full portal API integration is a future phase.

---

## What the Agent Handles Automatically

See `docs/AUTOMATION_ASSESSMENT.md` for the full breakdown.

**Short version**: Steps 1–5 (prospect → mockup delivery) are fully automated.
Steps 6–9 require Steele's approval at two gates:
1. Before the full build starts (confirm close, review intake form)
2. Before go-live (final QA review of the built site)

---

## Deployment Checklist (every client, from framework doc)

- [ ] Domain purchased and DNS pointed to server
- [ ] SSL certificate issued (automatic via Traefik)
- [ ] Google Analytics property created → ID added to site
- [ ] Google Business Profile claimed and linked
- [ ] sitemap.xml submitted to Google Search Console
- [ ] robots.txt verified
- [ ] Contact form → email delivery tested
- [ ] Mobile tested (iPhone + Android)
- [ ] Click-to-call tested on mobile
- [ ] Maps embed correct location
- [ ] Social links verified
- [ ] Square booking/ordering link tested (if applicable)
- [ ] Page speed check (target 90+ on PageSpeed Insights)
- [ ] Client portal account created and tested
- [ ] First invoice sent through portal
- [ ] Review ask sent (offer: 6 months free care plan)
