# Curbsite.co — Cost Estimate Per Client

Estimated API and service costs for one complete pipeline run (prospect → live site).

---

## Per-Lead Cost (Every Prospect Touched)

These costs apply to every lead that enters the pipeline, whether they convert or not.

| Operation | Model / Service | Tokens / Units | Unit Cost | Est. Cost |
|-----------|----------------|----------------|-----------|-----------|
| Lead scoring | GPT-4o-mini | ~300 in + 150 out | $0.15/$0.60 per 1M | **$0.000135** |
| Cold email draft | GPT-4o-mini | ~400 in + 350 out | $0.15/$0.60 per 1M | **$0.000270** |
| Follow-up ×2 (cached if same niche) | GPT-4o-mini | ~300 in + 250 out ×2 | $0.15/$0.60 per 1M | **$0.000240** |
| **Subtotal per untouched lead** | | | | **~$0.0006** |

With 1,000 prospects/month: ~$0.60/month in AI costs for prospecting.

---

## Per-Mockup Cost (Every Lead That Reaches Stage 5)

Mockups are sent to qualified leads after initial interest. Assume ~15% conversion from
outreach → mockup (i.e., 1 in 7 leads emailed gets a mockup).

| Operation | Model / Service | Tokens / Units | Unit Cost | Est. Cost |
|-----------|----------------|----------------|-----------|-----------|
| Mockup copy generation | GPT-4o-mini | ~500 in + 600 out | $0.15/$0.60 per 1M | **$0.00044** |
| Netlify deploy (free tier) | Netlify | — | Free | **$0.00** |
| Mockup delivery email | SMTP | 1 email | Free (Gmail app pass) | **$0.00** |
| Reply classification | GPT-4o-mini | ~200 in + 50 out ×2 | $0.15/$0.60 per 1M | **$0.00009** |
| **Subtotal per mockup sent** | | | | **~$0.0005** |

Assuming 150 mockups/month: ~$0.075/month in AI costs for mockup phase.

---

## Per-Conversion Cost (Paying Clients Only)

These costs only apply when a prospect says yes and a full site is built.

| Operation | Model / Service | Tokens / Units | Unit Cost | Low Est. | High Est. |
|-----------|----------------|----------------|-----------|----------|-----------|
| Full copy polish (GPT-4o) | GPT-4o | ~2,000 in + 1,500 out | $5/$15 per 1M | **$0.0325** | **$0.055** |
| Domain purchase | Namecheap | 1 domain (.com) | $10–15/yr | **$10.00** | **$15.00** |
| Hosting — Hostinger VPS | Hostinger | Shared VPS (per site slot) | ~$5/mo per site | **$5.00/mo** | **$10.00/mo** |
| Email sending (outreach) | Gmail SMTP | ~5 emails total | Free | **$0.00** | **$0.00** |
| **Subtotal per conversion (first month)** | | | | **~$15.03** | **~$25.06** |
| **Subtotal per conversion (ongoing/mo)** | | | | **~$5.00** | **~$10.00** |

Notes:
- GPT-4o costs assume a complete set of page copy. If you cache system prompts by niche
  (which the builder does), real costs are closer to the low estimate.
- Hostinger VPS cost is an allocation — one VPS can host 20–50 small static sites under
  Traefik. If you have 10 clients on a $50/mo VPS, that's $5/client/mo.
- Domain cost is one-time per year; renews at ~$12/yr.

---

## Full Pipeline Cost Summary (per paying client)

| Scenario | Total Cost (Year 1) | Notes |
|----------|---------------------|-------|
| **Low estimate** | **$75.10** | Shared VPS, cached copy, Namecheap domain |
| **High estimate** | **$135.12** | Dedicated VPS slot, full GPT-4o, GoDaddy domain |
| **Monthly recurring (care plan cost)** | **$5–10/mo** | Hosting only; no ongoing AI costs |

### Compared to Revenue

| Tier | Revenue | Year-1 Cost | **Net Margin** |
|------|---------|-------------|----------------|
| Entry | $800 + $75/mo care | $75–135 | **~$740–865 Y1** |
| Mid | $1,400 + $100/mo care | $75–135 | **~$1,340–1,465 Y1** |
| Top | $2,200 + $125/mo care | $75–135 | **~$2,090–2,265 Y1** |

The AI/hosting cost per client is less than 10% of revenue even at the high estimate.
The bottleneck is Steele's build time, not API costs.

---

## Monthly Operating Cost (at Scale)

Assuming 10 new clients/month, 100 active prospects in pipeline:

| Item | Monthly Cost |
|------|-------------|
| OpenAI (all pipeline steps) | ~$2–5 |
| Hostinger VPS (10 new sites) | ~$50–100 (scale VPS as needed) |
| Namecheap domains (10 new) | ~$10–15 (amortized) |
| Netlify (mockup previews, free tier) | $0 |
| Gmail SMTP | $0 |
| **Total** | **~$60–120/mo** |

At 10 clients × $1,400 avg revenue = $14,000/month gross. Operating costs are <1%.

---

## Token Optimization Notes

1. **Cache by niche**: All mockup copy prompts use `use_cache=True` with a niche-keyed
   system prompt. A "restaurant" in Kokomo and a "restaurant" in Indianapolis get
   slightly different user prompts but the same system prompt → partial cache benefit.
2. **GPT-4o only for final build copy**: The mockup phase uses GPT-4o-mini exclusively.
   GPT-4o is reserved for the final site build where quality matters.
3. **Reply classification**: Short prompts (~200 tokens in) — trivially cheap.
4. **Netlify free tier** handles up to 100 deploys/day and 100GB bandwidth — plenty
   for mockup previews of small HTML files.
