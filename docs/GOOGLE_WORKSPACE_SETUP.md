# Google Workspace Setup for getcurbsite.co

Cost: $6/month (Business Starter). This gives you steele@getcurbsite.co as a Gmail-powered mailbox for cold outreach.

---

## Step 1 — Start Google Workspace Trial

1. Go to **workspace.google.com**
2. Click **Get Started**
3. Enter your business info:
   - Business name: `Curbsite`
   - Number of employees: `Just you`
   - Country: United States
4. Click **Next**

---

## Step 2 — Use getcurbsite.co as Your Domain

1. On the "What's your business's domain?" screen, select **I have a domain I want to use**
2. Enter: `getcurbsite.co`
3. Click **Next**

---

## Step 3 — Create Your Admin Account

1. Enter your recovery email: `steele.stout@gmail.com`
2. Create the primary user:
   - Username: `steele`
   - Domain: `@getcurbsite.co` → full address will be `steele@getcurbsite.co`
   - Set a strong password
3. Agree to terms → click **Create Account**

---

## Step 4 — Verify Domain Ownership in Namecheap

Google will show you a TXT record like:
```
google-site-verification=abc123XYZ...
```

1. Copy that value
2. Open a new tab → go to **namecheap.com** → Domain List → **getcurbsite.co** → Manage → Advanced DNS
3. Add a new **TXT Record**:
   - Host: `@`
   - Value: paste the `google-site-verification=...` string
   - TTL: Automatic
4. Click **Save**
5. Return to Google Admin Console → click **Verify**
6. Google may take 5–15 minutes to detect the record

---

## Step 5 — Skip/Defer Additional Setup

After verification, Google will walk you through optional setup steps. You can:
- **Skip** adding users (just need the one account)
- **Skip** setting up storage/Drive for now
- Complete **MX record setup** (see GETCURBSITE_DNS_SETUP.md Step 1 — you may have already done this)

---

## Step 6 — Enable 2-Step Verification + Create App Password

You need an **App Password** (not your regular password) for SMTP auth in the outreach app.

1. Sign in to **myaccount.google.com** with steele@getcurbsite.co
2. Click **Security** in the left sidebar
3. Under "How you sign in to Google", click **2-Step Verification** → enable it (required before app passwords work)
4. After enabling 2SV, go back to **Security**
5. Scroll down to **App passwords** (or search "App passwords" in the search bar)
6. Click **App passwords**
7. In the dropdown, select:
   - Select app: **Mail**
   - Select device: **Other (Custom name)** → type `CurbsiteOutreach`
8. Click **Generate**
9. **Copy the 16-character password** shown (e.g., `abcd efgh ijkl mnop`)
   - Remove spaces: `abcdefghijklmnop`
   - This is your `OUTREACH_SMTP_PASS` — save it immediately, it won't be shown again

---

## Step 7 — Update Your .env File

Fill in the app password in your project's `.env`:

```env
OUTREACH_SMTP_PASS=abcdefghijklmnop    # your 16-char app password, no spaces
```

All other SMTP values are already set:
```env
OUTREACH_DOMAIN=getcurbsite.co
OUTREACH_EMAIL=steele@getcurbsite.co
OUTREACH_SMTP_HOST=smtp.gmail.com
OUTREACH_SMTP_PORT=587
OUTREACH_SMTP_USER=steele@getcurbsite.co
```

---

## Step 8 — Test the SMTP Connection

Run this from the project root to verify email sending works:

```bash
python -c "
import smtplib
from email.mime.text import MIMEText
msg = MIMEText('SMTP test from getcurbsite.co')
msg['Subject'] = 'SMTP Test'
msg['From'] = 'steele@getcurbsite.co'
msg['To'] = 'steele.stout@gmail.com'
with smtplib.SMTP('smtp.gmail.com', 587) as s:
    s.starttls()
    s.login('steele@getcurbsite.co', 'YOUR_APP_PASSWORD')
    s.send_message(msg)
    print('Success!')
"
```

---

## SMTP Settings Summary (for .env / app config)

| Setting | Value |
|---------|-------|
| Host | `smtp.gmail.com` |
| Port | `587` |
| Encryption | STARTTLS |
| Username | `steele@getcurbsite.co` |
| Password | 16-char app password (no spaces) |
| From name | `Steele from Curbsite` |
| From address | `steele@getcurbsite.co` |

---

## Google Admin Console — Enable DKIM Signing

After the domain is verified, activate DKIM signing in Google Admin:

1. Go to **admin.google.com**
2. Left sidebar: **Apps** → **Google Workspace** → **Gmail**
3. Click **Authenticate email**
4. Select domain: `getcurbsite.co`
5. You'll see a DKIM key section — click **Generate new record** (if needed) OR use the existing key you've already added to DNS (selector: `google`)
6. Click **Start authentication**
7. Status should change to **Authenticating**

> Note: The DKIM public key in DNS (Step 3 of GETCURBSITE_DNS_SETUP.md) must match what Google generates. If Google generates a different key, update the DNS DKIM record with Google's version instead.

---

## Checklist

- [ ] Google Workspace account created at workspace.google.com
- [ ] getcurbsite.co entered as the domain
- [ ] steele@getcurbsite.co created as primary user
- [ ] Domain verified via TXT record in Namecheap
- [ ] 2-Step Verification enabled on the account
- [ ] App password generated and saved to .env as OUTREACH_SMTP_PASS
- [ ] SMTP test email sent successfully
- [ ] DKIM signing activated in Google Admin Console
