# getcurbsite.co DNS Setup Checklist (Namecheap)

This domain is used exclusively for cold email outreach to protect curbsite.co reputation.

## Prerequisites
- Google Workspace account set up for getcurbsite.co (see GOOGLE_WORKSPACE_SETUP.md)
- Access to Namecheap account → getcurbsite.co

---

## How to Access DNS Settings in Namecheap

1. Log in at **namecheap.com**
2. Click **Domain List** in the left sidebar
3. Find **getcurbsite.co** → click **Manage**
4. Click the **Advanced DNS** tab
5. You will see a table of records — use **Add New Record** for each entry below

---

## Step 1 — MX Records (Email Routing → Google Workspace)

Add all 5 records. In the "Type" dropdown select **MX Record**.

| Type | Host | Value | Priority |
|------|------|-------|----------|
| MX   | @    | aspmx.l.google.com      | 1  |
| MX   | @    | alt1.aspmx.l.google.com | 5  |
| MX   | @    | alt2.aspmx.l.google.com | 5  |
| MX   | @    | alt3.aspmx.l.google.com | 10 |
| MX   | @    | alt4.aspmx.l.google.com | 10 |

> In Namecheap, "Host" = `@` (the root domain). TTL can be left as Automatic.

---

## Step 2 — SPF Record (Authorize Google to Send)

Select **TXT Record**.

| Type | Host | Value |
|------|------|-------|
| TXT  | @    | `v=spf1 include:_spf.google.com ~all` |

---

## Step 3 — DKIM Record (Email Signing Key)

Select **TXT Record**.

| Type | Host | Value |
|------|------|-------|
| TXT  | `google._domainkey` | `v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvAimLnbyyjxaGDSYeX+gSDzz9HRZrD7qTNH4dYJkTYTLpiIzLUmoi9G6xLKA9297NVWNj3B9aIjl72R+VPcpleJktq5P+7x/Vc6kNtYXfEWt0jrBQtDRRGHA2xzb2LO54prLxOMhpZtrt+zVqrr5AiEy6hyDDsrtyN9pB9ppS3URTcxKcw1LXBC5Her8eBbo72dkTUfBAJT+bhL4Mq3Uw7bRrH3nWEdeE23I6NR2c/Zpp/xHf9JMPItqwnzWrHRDhSw0Cao1hIHZhCgjyBZex0N3zwkHYNN7CnTVkMbVUSBq+E1E+HwcAw8fSpJ56XQ3Rvb2w8YpT9H87gVCuaGPSQIDAQAB` |

> **Host field**: enter `google._domainkey` exactly (Namecheap appends `.getcurbsite.co` automatically).  
> This corresponds to the selector `google` used in the app config (`DKIM_SELECTOR=google`).

---

## Step 4 — DMARC Record (Policy + Reporting)

Select **TXT Record**.

| Type | Host | Value |
|------|------|-------|
| TXT  | `_dmarc` | `v=DMARC1; p=quarantine; rua=mailto:steele.stout@gmail.com` |

> **Host field**: enter `_dmarc` (Namecheap appends `.getcurbsite.co`).  
> Reports will arrive at steele.stout@gmail.com. Change `p=quarantine` to `p=reject` after 30 days of clean reports.

---

## Step 5 — Google Workspace Domain Verification

When you set up Google Workspace (see GOOGLE_WORKSPACE_SETUP.md), Google will give you a unique TXT record to prove domain ownership. It looks like:

```
google-site-verification=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Add it as:

| Type | Host | Value |
|------|------|-------|
| TXT  | @    | `google-site-verification=<paste your code here>` |

> Copy the exact value from the Google Admin Console → Setup → Verify domain.

---

## Verification Commands (run after ~30 min for propagation)

```bash
# Check MX records
nslookup -type=MX getcurbsite.co 8.8.8.8

# Check SPF
nslookup -type=TXT getcurbsite.co 8.8.8.8

# Check DKIM
nslookup -type=TXT google._domainkey.getcurbsite.co 8.8.8.8

# Check DMARC
nslookup -type=TXT _dmarc.getcurbsite.co 8.8.8.8
```

---

## Summary Checklist

- [ ] 5 MX records added (priorities 1, 5, 5, 10, 10)
- [ ] SPF TXT record on `@`
- [ ] DKIM TXT record on `google._domainkey`
- [ ] DMARC TXT record on `_dmarc`
- [ ] Google Workspace verification TXT on `@`
- [ ] DNS verified with nslookup (~30–60 min propagation)
- [ ] Google Admin Console shows domain as verified
- [ ] Test email sent from steele@getcurbsite.co → steele.stout@gmail.com
