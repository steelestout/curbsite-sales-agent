# Email Infrastructure Setup Guide

Curbsite uses two dedicated services for two distinct email types. Using the
right tool for each prevents deliverability problems and keeps you compliant
with each service's Terms of Service.

---

## Architecture Overview

```
Cold outreach (prospects who haven't paid)  →  Our own SMTP on getcurbsite.co
Transactional (clients, go-live, alerts)    →  Resend on curbsite.co
```

| Email Type | Service | Domain |
|-----------|---------|--------|
| Initial cold email to prospects | Our SMTP + warmup | getcurbsite.co |
| Follow-up sequences (Day 3, Day 7) | Our SMTP + warmup | getcurbsite.co |
| Build started notification | Resend | curbsite.co |
| Site preview / approval request | Resend | curbsite.co |
| Payment confirmed | Resend | curbsite.co |
| Site live celebration email | Resend | curbsite.co |
| Review requests (14-day, 30-day) | Resend | curbsite.co |
| Referral drip (30-day post-live) | Resend | curbsite.co |
| Steele internal approval alerts | Resend | curbsite.co |
| Track B handoff zip delivery | Resend | curbsite.co |

### Cost comparison

| Approach | Cost |
|---------|------|
| **Our system** (Google Workspace $6/mo + ~$12/yr domain) | **~$7/mo** |
| Instantly.ai Hypergrowth | ~$37/mo |
| **Savings** | **~$30/mo · ~$360/yr** |

### Why NOT SendGrid / Mailgun / Amazon SES for cold outreach

All three prohibit unsolicited email in their ToS. Getting flagged:
- Terminates your entire account (including any transactional sends)
- Impacts your domain reputation permanently
- Loses all templates, stats, and history

Use SendGrid/Mailgun only for transactional email if you ever switch from Resend.

---

## Step 1 — Register your outreach domain (TODO)

> **TODO for Steele:** Register a dedicated cold outreach domain, e.g. `getcurbsite.co`.
> This domain absorbs all spam complaints so `curbsite.co` stays pristine.

**Instructions (Namecheap):**

1. Go to [namecheap.com](https://www.namecheap.com) and search for `getcurbsite.co`
   (or `getcurbsite.com` if .co is taken)
2. Add to cart → checkout (~$12/yr for .co, ~$10/yr for .com)
3. In Namecheap dashboard → Domain List → Manage → Advanced DNS
4. Add the DNS records from Steps 2 and 3 below
5. Set `OUTREACH_DOMAIN=getcurbsite.co` in `.env`

You keep `curbsite.co` only for the real website and transactional email.
If `getcurbsite.co` ever gets a spam complaint, you can let it age and register
a new one — your main brand is untouched.

---

## Step 2 — Set up Google Workspace on the outreach domain

**Cost:** $6/month per user (one inbox is enough to start)

1. Go to [workspace.google.com](https://workspace.google.com) → Get started
2. Enter `getcurbsite.co` as your domain
3. Create the sending address: `steele@getcurbsite.co`
4. Follow the Google Workspace DNS setup wizard — it will ask you to add:
   - An MX record (routes mail to Google)
   - A TXT verification record

5. Once verified, add a Google Workspace App Password for SMTP:
   - myaccount.google.com → Security → 2-Step Verification (enable first)
   - App Passwords → Other → "Curbsite outreach" → Generate
   - Copy the 16-character password

6. Add to `.env`:
   ```
   SENDER_ACCOUNTS=[{"email":"steele@getcurbsite.co","smtp_host":"smtp.gmail.com","smtp_port":587,"smtp_pass":"xxxx xxxx xxxx xxxx","from_name":"Steele","warmup_day":1}]
   OUTREACH_EMAIL=steele@getcurbsite.co
   OUTREACH_DOMAIN=getcurbsite.co
   ```

---

## Step 3 — Configure SPF, DKIM, and DMARC on the outreach domain

All records go on `getcurbsite.co` (not curbsite.co).

### SPF

```
Type:  TXT
Name:  @   (or getcurbsite.co)
Value: v=spf1 include:_spf.google.com ~all
```

### DKIM (Google Workspace)

1. Google Workspace Admin → Apps → Gmail → Authenticate email
2. Select domain: `getcurbsite.co`, key length: 2048 bits
3. Click "Generate new record"
4. Add the TXT record it shows you (name is `google._domainkey.getcurbsite.co`)
5. Back in Admin: click "Start authentication"
6. Set `DKIM_SELECTOR=google` in `.env`

### DMARC

```
Type:  TXT
Name:  _dmarc   (or _dmarc.getcurbsite.co)
Value: v=DMARC1; p=quarantine; rua=mailto:steele.stout@gmail.com
```

### Verify DNS health

```bash
python -m src.outreach.domain_reputation getcurbsite.co
```

Expected output: all three checks (SPF, DKIM, DMARC) show `pass`.

---

## Step 4 — Set up Resend for transactional email

**Cost:** Free up to 3,000 emails/month. $20/month for 50,000.

1. Sign up at [resend.com](https://resend.com)

2. Add and verify `curbsite.co`:
   - Resend dashboard → Domains → Add domain → `curbsite.co`
   - Add the DNS records Resend gives you
   - Recommended sending address: `steele@curbsite.co`

3. Create an API key:
   - Resend dashboard → API Keys → Create API Key
   - Add to `.env`: `RESEND_API_KEY=re_...`

4. Set your From address:
   ```
   RESEND_FROM_EMAIL=Steele @ Curbsite <steele@curbsite.co>
   ```

5. Install the Python SDK:
   ```bash
   pip install resend
   ```

---

## Warmup Schedule

Start at Day 1 when you first connect a new inbox. Increment `warmup_day` by 1
each calendar day. The system enforces these caps automatically.

| Period | Daily Cap | `warmup_day` value |
|--------|----------|-------------------|
| Days 1–7 | 5/day | 1–7 |
| Days 8–14 | 15/day | 8–14 |
| Days 15–21 | 30/day | 15–21 |
| Day 22+ | 50/day | 22+ |

**When adding a second inbox:** set its `warmup_day` to 1 in `SENDER_ACCOUNTS`.
The system tracks each account independently. After 3+ weeks, both accounts are
warmed and you're sending 100/day combined.

Check warmup status:
```bash
python -m src.outreach.warmup --status
```

---

## Deliverability Features (all automatic)

| Feature | How it works |
|---------|-------------|
| Business hours gate | Only sends 8am–6pm Central (Mon–Fri) |
| Random delays | 45–180 seconds between sends |
| Domain cooldown | Won't send to the same prospect domain twice per hour |
| DB queue | When all accounts hit daily cap, email is held until next morning |
| CAN-SPAM footer | Physical address + unsubscribe link on every cold email |
| List-Unsubscribe header | One-click unsubscribe for email clients that support it |
| Hard bounce blocking | Bounced addresses are never retried |

---

## CAN-SPAM Compliance

Required settings in `.env`:

```bash
# Physical mailing address required by CAN-SPAM §5
CURBSITE_ADDRESS=Curbsite.co · Kokomo, IN 46902 · United States

# Secret for signing unsubscribe tokens — generate once, never change
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
UNSUBSCRIBE_SECRET=<generate this>
```

The `/unsubscribe` endpoint (registered as a Flask Blueprint) handles one-click
unsubscribes from cold outreach emails. Resend handles transactional unsubscribes
natively through its dashboard.

---

## .env Quick-Start Checklist

```bash
# ── Outreach domain (cold email) ──────────────────────────────────────────────
OUTREACH_DOMAIN=getcurbsite.co
OUTREACH_EMAIL=steele@getcurbsite.co
SENDER_ACCOUNTS=[{"email":"steele@getcurbsite.co","smtp_host":"smtp.gmail.com","smtp_port":587,"smtp_pass":"your-app-password","from_name":"Steele","warmup_day":1}]
WARMUP_DAY=1                    # Set to 1 on day one; increment by 1 each day
SENDING_DOMAIN=getcurbsite.co
DKIM_SELECTOR=google

# ── Resend (transactional) ────────────────────────────────────────────────────
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=Steele @ Curbsite <steele@curbsite.co>

# ── CAN-SPAM compliance ───────────────────────────────────────────────────────
CURBSITE_ADDRESS=Curbsite.co · Kokomo, IN 46902 · United States
UNSUBSCRIBE_SECRET=<python -c "import secrets; print(secrets.token_hex(32))">
```

---

## Testing

```bash
# Check DNS for the outreach domain
python -m src.outreach.domain_reputation getcurbsite.co

# Dry-run a cold email (no actual send)
python -c "
from src.outreach.sender import send_email
send_email(1, 'steele.stout@gmail.com', 'Test subject', 'Test body', dry_run=True)
print('Sender OK')
"

# Verify Resend is configured
python -c "
from src.notifications.transactional import send_transactional
send_transactional('steele.stout@gmail.com', 'Test', '<p>Hello</p>', 'Hello')
print('Resend OK')
"

# Check warmup status
python -m src.outreach.warmup --status
```
