# Email Infrastructure Setup Guide

Curbsite uses two dedicated services for two distinct email types. Using the
right tool for each prevents deliverability problems and keeps you compliant
with each service's Terms of Service.

---

## Two-Service Architecture

```
Cold outreach (prospects)  →  Instantly.ai
Transactional (clients)    →  Resend
Both missing               →  SMTP fallback (development/testing only)
```

| Email Type | Service | Why |
|-----------|---------|-----|
| Initial cold email to prospects | **Instantly.ai** | Purpose-built for cold email; handles warming, rotation, compliance |
| Follow-up sequences (Day 3, Day 7) | **Instantly.ai** | Multi-step campaign sequences |
| Build started notification | **Resend** | Client expects this after paying deposit |
| Site preview ready / approval | **Resend** | Triggered by Steele's approval action |
| Payment confirmed | **Resend** | Triggered by Stripe webhook |
| Site live celebration email | **Resend** | Client expects this at launch |
| Review requests (14-day, 30-day) | **Resend** | Warm relationship email |
| Referral drip (30-day post-live) | **Resend** | Warm relationship email |
| Steele internal approval alerts | **Resend** | Internal notification |
| Track B handoff zip delivery | **Resend** | Client deliverable email |

### Why NOT SendGrid / Mailgun / Amazon SES for cold outreach

All three prohibit unsolicited email in their ToS. Getting flagged:
- Terminates your entire account (including any transactional sends)
- Impacts your domain reputation permanently
- Loses all templates, stats, and history

Use SendGrid/Mailgun only for transactional email if you ever switch from Resend.

---

## Service 1: Resend (Transactional)

**Cost:** Free up to 3,000 emails/month. $20/month for 50,000.  
**Best for:** Any email a paying client expects to receive.

### Setup

1. Sign up at [resend.com](https://resend.com)

2. Add and verify your sending domain:
   - Resend dashboard → Domains → Add domain
   - Add the DNS records Resend gives you (they walk you through it)
   - Recommended sending address: `steele@curbsite.co` or `steele@mail.curbsite.co`

3. Create an API key:
   - Resend dashboard → API Keys → Create API Key
   - Copy and add to `.env`: `RESEND_API_KEY=re_...`

4. Set your From address in `.env`:
   ```
   RESEND_FROM_EMAIL=Steele @ Curbsite <steele@curbsite.co>
   ```

5. Install the Python SDK:
   ```bash
   pip install resend
   ```

### What Resend handles automatically
- Delivery tracking (opens, clicks if enabled)
- Bounce handling
- Unsubscribe compliance for transactional email
- Domain reputation monitoring
- Beautiful delivery logs in the dashboard

---

## Service 2: Instantly.ai (Cold Outreach)

**Cost:** ~$37/month (Hypergrowth) — unlimited sending accounts + warming included.  
**Best for:** Any email to a prospect who hasn't signed up or paid yet.

### Why Instantly over raw SMTP
- **Auto-warming:** New accounts warm up automatically — no manual warmup_day tracking needed
- **Account rotation:** Connects multiple inboxes and rotates between them automatically
- **Reply detection:** Detects when prospects reply and pauses follow-ups
- **Deliverability dashboard:** Real-time spam score, bounce rate, and health metrics
- **Unsubscribe built-in:** One-click unsubscribe handled automatically by Instantly
- **Multi-step sequences:** Build Day 0 → Day 3 → Day 7 sequences in the UI

### Setup

1. Sign up at [instantly.ai](https://instantly.ai) (Hypergrowth plan recommended)

2. Connect your sending inboxes:
   - Settings → Email Accounts → Connect Account
   - Connect your Google Workspace accounts (e.g., `outreach@mail.curbsite.co`)
   - Instantly will automatically warm them up over 4 weeks

3. (Recommended) Create a cold outreach campaign:
   - Campaigns → New Campaign → "Curbsite Cold Outreach"
   - Add your email sequence: Day 0 initial, Day 3 follow-up, Day 7 final
   - Use `{{first_name}}`, `{{business_name}}`, etc. for personalization
   - Set the campaign to active

4. Get your API key:
   - Settings → Integrations → API → Generate
   - Add to `.env`: `INSTANTLY_API_KEY=...`

5. Get your campaign ID:
   - Open the campaign → Settings → Copy campaign ID from the URL
   - Add to `.env`: `INSTANTLY_CAMPAIGN_ID=...`
   - If left blank, emails go via direct-send API instead of a campaign

6. Set your From address:
   ```
   INSTANTLY_FROM_EMAIL=outreach@mail.curbsite.co
   ```

### Two send modes

**Campaign mode** (`INSTANTLY_CAMPAIGN_ID` set — recommended):
- Our code calls `send_email()` → adds prospect to the Instantly campaign
- Instantly handles send timing, warming, rotation, and follow-up steps
- Reply detection automatically removes prospects from the sequence
- Best for systematic cold outreach sequences

**Direct send mode** (`INSTANTLY_CAMPAIGN_ID` not set):
- Our code calls Instantly's `/api/v2/emails/send` endpoint
- Sends immediately through a connected inbox
- Use for one-off sends outside a regular sequence

---

## SMTP Fallback (No API Keys Set)

When neither `INSTANTLY_API_KEY` nor `RESEND_API_KEY` is set, all email falls
back to raw SMTP using `SMTP_HOST/USER/PASS` from `.env`. This path still
enforces warmup limits and deliverability gates but requires manual DNS setup.

**Only use SMTP fallback for:**
- Local development and testing
- First week while you're getting Resend/Instantly set up

**SMTP DNS requirements** (if you end up using SMTP for cold outreach):

Never send cold email from your main domain (`curbsite.co`). Use a subdomain:
- `mail.curbsite.co`
- `outreach.curbsite.co`

### SPF record
```
Type: TXT
Name: mail.curbsite.co
Value: v=spf1 include:_spf.google.com ~all
```

### DKIM (Google Workspace)
1. Google Workspace Admin → Apps → Gmail → Authenticate email
2. Select domain `mail.curbsite.co`, key length 2048
3. Generate record → add TXT at `google._domainkey.mail.curbsite.co`
4. Click "Start authentication"

### DMARC
```
Type: TXT
Name: _dmarc.mail.curbsite.co
Value: v=DMARC1; p=quarantine; rua=mailto:steele.stout@gmail.com
```

### Verify DNS
```bash
python -m src.outreach.domain_reputation mail.curbsite.co
```

---

## Warmup Schedule (SMTP fallback only)

When using Instantly, warmup is handled automatically. When using SMTP directly:

| Period | Daily Cap |
|--------|----------|
| Days 1–7 | 5/day |
| Days 8–14 | 15/day |
| Days 15–21 | 30/day |
| Day 22+ | 50/day |

Track warmup: `python -m src.outreach.warmup --status`

---

## CAN-SPAM Compliance

Handled automatically for all paths:
- **Instantly.ai:** manages unsubscribes natively in the platform
- **Resend + SMTP:** `src/outreach/compliance.py` injects footer and `List-Unsubscribe` header
- **Dashboard `/unsubscribe` endpoint:** handles one-click unsubscribes from raw SMTP emails

Physical address (required by CAN-SPAM §5):
```
CURBSITE_ADDRESS=Curbsite.co · Kokomo, IN 46902 · United States
```

---

## .env Quick-Start Checklist

```bash
# Resend (transactional)
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=Steele @ Curbsite <steele@curbsite.co>

# Instantly (cold outreach)
INSTANTLY_API_KEY=...
INSTANTLY_CAMPAIGN_ID=...          # recommended
INSTANTLY_FROM_EMAIL=outreach@mail.curbsite.co

# CAN-SPAM compliance
CURBSITE_ADDRESS=Curbsite.co · Kokomo, IN 46902 · United States
UNSUBSCRIBE_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(32))">
```

---

## Testing

```bash
# Verify Resend is configured
python -c "
import os; os.environ['RESEND_API_KEY']='your-key'
from src.notifications.transactional import send_transactional
send_transactional('steele.stout@gmail.com', 'Test', '<p>Hello</p>', 'Hello')
print('Resend OK')
"

# Verify Instantly is configured
python -c "
import os; os.environ['INSTANTLY_API_KEY']='your-key'
from src.outreach.sender import send_email
send_email(1, 'steele.stout@gmail.com', 'Test subject', 'Test body', dry_run=True)
print('Instantly OK')
"

# Check DNS for SMTP fallback
python -m src.outreach.domain_reputation mail.curbsite.co
```
