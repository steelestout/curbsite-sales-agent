# Stripe Webhook Setup

The `src/payments/stripe_webhook.py` Flask app handles automatic pipeline triggers based on Stripe payment events.

## Events handled

| Stripe event | Trigger | Result |
|---|---|---|
| `payment_intent.succeeded` (deposit) | Client pays 50% upfront | Lead → `agreed`, build starts, Steele notified |
| `payment_intent.succeeded` (final) | Client pays final 50% | Lead → `deployed`, golive triggered |

---

## 1. Install Stripe SDK

```bash
pip install stripe
```

---

## 2. Get your API keys

1. Go to [https://dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys)
2. Copy your **Secret key** (`sk_live_...`)
3. Add to `.env`:

```
STRIPE_SECRET_KEY=sk_live_...
```

---

## 3. Register the webhook endpoint

1. Go to [https://dashboard.stripe.com/webhooks](https://dashboard.stripe.com/webhooks)
2. Click **Add endpoint**
3. Set endpoint URL: `https://curbsite.co/stripe/webhook`
4. Select event: `payment_intent.succeeded`
5. Copy the **Signing secret** (`whsec_...`)
6. Add to `.env`:

```
STRIPE_WEBHOOK_SECRET=whsec_...
```

---

## 4. Deploy the webhook server on Hostinger VPS

SSH into the VPS and run:

```bash
cd /var/www/curbsite-sales-agent
pip install -r requirements.txt
gunicorn -w 2 -b 0.0.0.0:5001 'src.payments.stripe_webhook:app' \
  --daemon --log-file /var/log/curbsite-stripe.log
```

Add nginx proxy (in your Hostinger nginx site config):

```nginx
location /stripe/webhook {
    proxy_pass http://127.0.0.1:5001/webhook;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

---

## 5. Create Payment Intents with metadata

When you create a Stripe payment link or checkout session for a client, include metadata so the webhook knows which lead it belongs to:

```python
import stripe

# 50% deposit
pi = stripe.PaymentIntent.create(
    amount=int(deposit_amount_usd * 100),  # cents
    currency="usd",
    metadata={
        "lead_id": str(lead_id),
        "payment_type": "deposit",
    },
)

# Final 50%
pi = stripe.PaymentIntent.create(
    amount=int(final_amount_usd * 100),
    currency="usd",
    metadata={
        "lead_id": str(lead_id),
        "payment_type": "final",
    },
)
```

Store the payment intent ID on the lead:

```bash
# In the CRM:
UPDATE leads SET stripe_deposit_id='pi_xxx', stripe_payment_url='https://...' WHERE id=42;
```

---

## 6. What happens automatically

### 50% deposit received:
1. Lead status → `agreed`
2. Client receives "Build Started" email
3. `site_builder.py` runs in background thread
4. After build: Steele receives preview email with **Approve / Request Changes** buttons

### Steele clicks Approve:
1. Client receives "Site Preview Ready" email with preview link + final payment link

### Final 50% received:
1. Lead status → `deployed`
2. Client receives "Payment Confirmed" email
3. `golive.py` runs in background thread
4. When live: client receives "Site Live" email with URL + portal login

---

## 7. Test with Stripe CLI (no real charges)

```bash
# Install Stripe CLI
stripe login

# Forward events to local webhook server
stripe listen --forward-to localhost:5001/webhook

# Trigger a test event
stripe trigger payment_intent.succeeded \
  --add payment_intent:metadata.lead_id=1 \
  --add payment_intent:metadata.payment_type=deposit
```

---

## 8. Failure handling

If the build or golive fails inside the background thread, Steele receives an alert email with the error and manual recovery instructions:

```bash
# Manual build fallback
python -m src.orchestrator --step build --lead-id {id}

# Manual approve (bypass email link)
python -m src.orchestrator --step approve-build --lead-id {id}

# Manual golive
python -m src.orchestrator --step golive --lead-id {id}
```
