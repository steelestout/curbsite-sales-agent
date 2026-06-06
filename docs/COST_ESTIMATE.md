# Curbsite.co — Cost Estimate Per Client

Estimated API and service costs for one complete pipeline run (prospect → live site).

**Deployment model as of 2026-06-06:**
- **Track A** (client has maintenance plan) → dedicated Hetzner VPS per client
- **Track B** (no maintenance plan) → zip handoff, client self-hosts

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

## Per-Mockup Cost (Every Scored Lead — Pre-Outreach)

Mockups are now generated **before** the first email. The URL is embedded in
the cold email as the hook. Assume 100% of emailed leads get a mockup.

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

### Track A — Client has maintenance plan (dedicated Hetzner VPS)

| Operation | Model / Service | Tokens / Units | Unit Cost | Low Est. | High Est. |
|-----------|----------------|----------------|-----------|----------|-----------|
| Full copy polish (GPT-4o) | GPT-4o | ~2,000 in + 1,500 out | $5/$15 per 1M | **$0.033** | **$0.055** |
| Domain purchase | Namecheap | 1 domain (.com) | $10–15/yr | **$10.00** | **$15.00** |
| **VPS — Standard (CX22)** | Hetzner | 2 vCPU / 4GB / 40GB SSD | ~**$5/mo** | **$5.00/mo** | — |
| **VPS — Performance (CX32)** | Hetzner | 4 vCPU / 8GB / 80GB SSD | ~**$9/mo** | — | **$9.00/mo** |
| Email sending (outreach) | Gmail SMTP | ~5 emails total | Free | **$0.00** | **$0.00** |
| **Subtotal (first month)** | | | | **~$15.03** | **~$24.06** |
| **Subtotal (ongoing/mo)** | | | | **~$5.00** | **~$9.00** |

**Standard VPS** (CX22, ~$5/mo): Salons, contractors, auto shops, fitness, photographers
— brochure + booking sites, low concurrent load.

**Performance VPS** (CX32, ~$9/mo): Restaurants mid/top tier with online ordering
— higher concurrent load at lunch/dinner rush.

Compared to competitors:
- Vultr: $6/mo (Standard) / $12/mo (Performance)  
- DigitalOcean: $6/mo (Standard) / $12/mo (Performance)  
- **Hetzner wins at every tier.**

---

### Track B — No maintenance plan (zip handoff)

| Operation | Model / Service | Tokens / Units | Unit Cost | Est. Cost |
|-----------|----------------|----------------|-----------|-----------|
| Full copy polish (GPT-4o) | GPT-4o | ~2,000 in + 1,500 out | $5/$15 per 1M | **$0.033** |
| Domain (client buys own) | — | — | — | **$0** (not our cost) |
| Hosting (client hosts own) | — | — | — | **$0** (not our cost) |
| SMTP handoff email | Gmail | 1 email + zip attachment | Free | **$0.00** |
| **Subtotal per Track B conversion** | | | | **~$0.03** |

Track B has near-zero cost to us — client self-hosts. The trade-off is no recurring
revenue beyond the one-time build fee.

---

### Notes:
- GPT-4o costs assume a complete set of page copy. If you cache system prompts by niche
  (which the builder does), real costs are closer to the low estimate.
- Domain cost is one-time per year; renews at ~$12/yr.
- VPS is provisioned per client — not a shared slot. Each client has their own isolated server.

---

## Full Pipeline Cost Summary (per paying client)

### Track A (with maintenance plan)

| Scenario | Total Cost (Year 1) | Notes |
|----------|---------------------|-------|
| **Low (salon/contractor)** | **$75.03** | Standard CX22 ~$5/mo, cached copy, Namecheap domain |
| **High (restaurant, online ordering)** | **$123.06** | Performance CX32 ~$9/mo, full GPT-4o |
| **Monthly recurring (hosting cost)** | **$5–9/mo** | Hetzner VPS only; no ongoing AI costs |

### Track B (no maintenance plan)

| Scenario | Total Cost | Notes |
|----------|-----------|-------|
| **All niches** | **~$10.03** | Domain optional ($10–15/yr), GPT-4o copy, no hosting cost |

---

### Compared to Revenue (updated per-niche pricing)

**Track A — With Care Plan**

| Niche | Mid Tier Revenue | Monthly Care | Year-1 Cost | **Net Margin Y1** |
|-------|-----------------|--------------|-------------|-------------------|
| Restaurant (mid) | $1,800 | $100/mo | ~$123 | **~$2,877** |
| Salon (mid) | $1,500 | $100/mo | ~$75 | **~$2,625** |
| Auto (mid) | $1,600 | $100/mo | ~$75 | **~$2,725** |
| Contractor (mid) | $1,900 | $100/mo | ~$75 | **~$3,025** |
| Fitness (mid) | $1,900 | $100/mo | ~$75 | **~$3,025** |

**Track B — One-Time Build, No Care Plan**

| Niche | Mid Tier Revenue | Year-1 Cost | **Net Margin Y1** |
|-------|-----------------|-------------|-------------------|
| Restaurant (mid) | $1,800 | ~$10 | **~$1,790** |
| Salon (mid) | $1,500 | ~$10 | **~$1,490** |
| Contractor (mid) | $1,900 | ~$10 | **~$1,890** |

Track B has higher per-project margin but no recurring revenue. Push Track A — the
$75–125/mo care plan is the business model.

---

## Monthly Operating Cost (at Scale)

Assuming 10 new Track A clients/month, 200 active prospects in pipeline:

| Item | Monthly Cost |
|------|-------------|
| OpenAI (all pipeline steps) | ~$3–8 |
| Hetzner VPS × 10 new Standard clients | ~$50/mo new (accumulates) |
| Hetzner VPS × 2 new Performance clients (restaurants) | ~$18/mo new |
| Namecheap domains (10 new) | ~$10–15 (amortized) |
| Netlify (mockup previews, free tier) | $0 |
| Gmail SMTP | $0 |
| **Total new client cost/mo** | **~$80–90/mo** |

At 10 clients × $1,700 avg mid revenue = **$17,000 new revenue**.
Operating costs are **<0.6%** of revenue.

After 12 months × 10 clients × $100 avg care plan = **$12,000/mo recurring.**

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
