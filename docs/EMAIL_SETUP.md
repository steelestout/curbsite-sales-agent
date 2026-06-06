# Email Deliverability Setup Guide

Complete setup guide for sending cold outreach at scale without landing in spam.
Follow every step — skipping any one of them meaningfully hurts deliverability.

---

## The #1 Rule: Never Send Cold Email from Your Main Domain

**curbsite.co** is your brand. One spam complaint from cold outreach can destroy
your email reputation for the entire domain — affecting your own business emails,
client communications, and every future send.

Instead, send cold outreach from a **subdomain**:
- `mail.curbsite.co`  (recommended)
- `outreach.curbsite.co`
- `hello.curbsite.co`

Your main domain stays clean. If the sending subdomain ever gets flagged, you
create a new one while your brand domain remains unaffected.

---

## Recommended Sending Infrastructure

### Option A: Google Workspace (Best Deliverability — Recommended)

**Cost:** $6/month per account  
**Why:** Gmail-to-Gmail delivery is treated with highest trust by Gmail's filters,
which is where most small business owners have their email.

**Setup:**
1. Go to [workspace.google.com](https://workspace.google.com) → Get started
2. Use your sending subdomain as the domain (e.g., `mail.curbsite.co`)
3. Create a sending account: `outreach@mail.curbsite.co` or `steele@mail.curbsite.co`
4. Enable 2FA, then generate an **App Password**:
   - Google Account → Security → 2-Step Verification → App passwords
   - Select app: "Mail", device: "Other" → name it "Curbsite Outreach"
   - Copy the 16-char password — this goes in `.env` as `SMTP_PASS`
5. Add to `.env`: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`
6. Set up SPF, DKIM, and DMARC (see DNS Setup below)

**Limits:** 500 emails/day per account (vs. 25 for free Gmail). We cap at 50/day
for cold outreach to stay well below Gmail's spam-detection thresholds.

---

### Option B: Instantly.ai or Smartlead (Fully Managed — Easiest)

**Cost:** $37–97/month  
**Why:** These platforms handle inbox warming, account rotation, and deliverability
monitoring automatically. Zero DNS setup friction. Recommended if you want to
focus on sales rather than infrastructure.

- [Instantly.ai](https://instantly.ai) — best UI, auto-warming, supports Google Workspace + Outlook
- [Smartlead.ai](https://smartlead.ai) — similar features, slightly cheaper

**Setup:**
1. Sign up for Instantly.ai
2. Connect your Google Workspace accounts
3. Add `INSTANTLY_API_KEY=your_key` to `.env`
4. Instantly handles warming, rotation, and bounce tracking

---

### What NOT to Use for Cold Outreach

| Service | Use it for | Do NOT use for |
|---------|-----------|----------------|
| SendGrid | Transactional email (receipts, go-live alerts, client notifications) | Cold outreach — they will ban your account |
| Mailgun | Transactional email | Cold outreach |
| Amazon SES | Bulk transactional email | Cold outreach |
| Free Gmail (@gmail.com) | Personal email | Outreach — 500/day limit AND terrible deliverability for cold email |

SendGrid and Mailgun are excellent services — but their Terms of Service prohibit
cold email, and their shared IP pools are over-used for spam, hurting deliverability.

---

## DNS Setup (Required for Every Sending Domain)

All three records must be configured before sending a single cold email.
Run `python -m src.outreach.domain_reputation mail.curbsite.co` to verify.

### 1. Sending Subdomain DNS

If sending from `mail.curbsite.co`, add this to your DNS (at Namecheap, Cloudflare, etc.):

```
Type: A (or CNAME)
Name: mail
Value: (your sending server IP or Google's MX)
```

For Google Workspace sending, you'll set up MX records pointing to Google's servers.
Google Workspace Admin → Domains → Add domain → `mail.curbsite.co` → follow their DNS wizard.

---

### 2. SPF Record

**What it does:** Tells receiving servers which IPs are authorized to send email
for your domain. Without SPF, your emails are likely to be marked spam.

**For Google Workspace:**
```
Type: TXT
Name: mail.curbsite.co  (or @ if your sending domain is the root)
Value: v=spf1 include:_spf.google.com ~all
TTL: 3600
```

**For SendGrid (transactional only):**
```
Value: v=spf1 include:sendgrid.net ~all
```

**Verify:**
```bash
nslookup -type=TXT mail.curbsite.co
# Should show: "v=spf1 include:_spf.google.com ~all"
```

---

### 3. DKIM Record

**What it does:** Cryptographically signs outgoing emails so recipients can verify
they weren't tampered with in transit. Without DKIM, many filters auto-reject.

**Generate your DKIM key (Google Workspace):**
1. Google Workspace Admin Console → Apps → Google Workspace → Gmail
2. Click "Authenticate email"
3. Select your sending domain: `mail.curbsite.co`
4. DKIM key bit length: 2048
5. Click "Generate new record"
6. Copy the TXT record value — it looks like `v=DKIM1; k=rsa; p=MIIBIjANBg...`

**Add to DNS:**
```
Type: TXT
Name: google._domainkey.mail.curbsite.co
Value: v=DKIM1; k=rsa; p=<your-key-here>
TTL: 3600
```

**Enable DKIM in Workspace:**
Back in Google Admin → Gmail → Authenticate email → click "Start authentication"

**Verify:**
```bash
python -m src.outreach.domain_reputation mail.curbsite.co google
# Should show: DKIM: OK
```

---

### 4. DMARC Record

**What it does:** Tells receiving servers what to do when an email fails SPF/DKIM
checks. Protects your domain from spoofing and gives you visibility into abuse.

**Start with monitoring (p=none), then tighten:**

**Step 1 — Monitoring only (first 2 weeks):**
```
Type: TXT
Name: _dmarc.mail.curbsite.co
Value: v=DMARC1; p=none; rua=mailto:steele.stout@gmail.com
TTL: 3600
```

**Step 2 — Quarantine (after 2 weeks of clean reports):**
```
Value: v=DMARC1; p=quarantine; rua=mailto:steele.stout@gmail.com
```

**Step 3 — Reject (once everything is confirmed working):**
```
Value: v=DMARC1; p=reject; rua=mailto:steele.stout@gmail.com
```

`rua=` receives aggregate XML reports daily — useful for spotting misconfigurations.

**Verify:**
```bash
nslookup -type=TXT _dmarc.mail.curbsite.co
# Should show: "v=DMARC1; p=quarantine; ..."
```

---

### 5. MX Records

Required if you want replies to land in your Google Workspace inbox.

**Google Workspace MX records for `mail.curbsite.co`:**
```
Type: MX  Priority: 1   Value: aspmx.l.google.com
Type: MX  Priority: 5   Value: alt1.aspmx.l.google.com
Type: MX  Priority: 5   Value: alt2.aspmx.l.google.com
Type: MX  Priority: 10  Value: alt3.aspmx.l.google.com
Type: MX  Priority: 10  Value: alt4.aspmx.l.google.com
TTL: 3600
```

---

## Inbox Warming Schedule

Never start sending at full volume with a new account. ISPs watch for new accounts
that immediately send hundreds of emails — it's a strong spam signal.

The warmup schedule enforced by `src/outreach/warmup.py`:

| Period | Daily Limit |
|--------|------------|
| Week 1 (days 1–7) | 5 emails/day |
| Week 2 (days 8–14) | 15 emails/day |
| Week 3 (days 15–21) | 30 emails/day |
| Week 4+ (days 22+) | 50 emails/day |

**Configure in `.env`:**
```bash
SENDER_ACCOUNTS=[{"email":"outreach@mail.curbsite.co","smtp_host":"smtp.gmail.com",
  "smtp_port":587,"smtp_pass":"your-app-password","from_name":"Steele @ Curbsite",
  "warmup_day":1}]
```

**Increment warmup_day daily** (bump `warmup_day` by 1 in `.env` each morning).
At day 22, the account is fully warmed and the 50/day cap applies.

**Check warmup status:**
```bash
python -m src.outreach.warmup --status
```

---

## Sending Limits and Rules

Enforced by `src/outreach/deliverability.py`:

- **Business hours only:** 8am–6pm Central (no sends at night)
- **Random 45–180s delay** between each send (mimics human pacing)
- **One domain per hour:** Never email two addresses at the same company in the same hour
- **Daily hard cap:** Determined by warmup_day (max 50/day per account)
- **Account rotation:** Multiple accounts round-robin automatically via `SENDER_ACCOUNTS`

---

## CAN-SPAM Compliance Checklist

Every email sent through `sender.py` automatically includes:

- [x] Physical mailing address in footer (`CURBSITE_ADDRESS` from `.env`)
- [x] One-click unsubscribe link (HMAC-signed, handled by `/unsubscribe` endpoint)
- [x] `List-Unsubscribe` and `List-Unsubscribe-Post` headers
- [x] `X-Mailer` header set to look like a real email client

You are responsible for:
- [ ] Not emailing anyone who has previously opted out (handled automatically — CRM blocks it)
- [ ] Honoring unsubscribe requests within 10 business days (handled immediately by the system)
- [ ] Keeping your physical address current in `CURBSITE_ADDRESS`

---

## Pre-Send Checklist

Before starting any outreach campaign:

1. **Verify DNS:**
   ```bash
   python -m src.outreach.domain_reputation mail.curbsite.co
   ```

2. **Check warmup status:**
   ```bash
   python -m src.outreach.warmup --status
   ```

3. **Test with dry run:**
   ```bash
   python -m src.outreach.sender --dry-run --lead-id 1
   ```

4. **Confirm dashboard deliverability tab** shows bounce rate <2% and unsub rate <0.5%

5. **Start with 3–5 test sends** to your own email addresses before going live

---

## Troubleshooting

**Emails landing in spam:**
- Check SPF/DKIM/DMARC with the domain checker
- Ensure you're not sending more than your warmup limit allows
- Check for spam trigger words in subject/body
- Switch from HTML to plain text for initial emails

**Account getting flagged:**
- Reduce volume immediately
- Check bounce rate — if >2%, stop and clean your list
- Add more sending accounts and spread the load

**DNS propagation:**
- DNS changes can take up to 48 hours to propagate globally
- Test propagation: [mxtoolbox.com/SuperTool.aspx](https://mxtoolbox.com/SuperTool.aspx)
- Use `nslookup -type=TXT your-domain.com` to check from your machine
