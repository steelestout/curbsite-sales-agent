# Curbsite.co — Automation Assessment

Honest breakdown of what the agent can do alone, what needs Steele, and what *should*
involve Steele even when automation is technically possible.

---

## Fully Automated (No Human Needed)

| Step | What Happens | Why It's Safe to Automate |
|------|-------------|--------------------------|
| Lead scraping | Yelp/Google → CRM | Read-only, no external side effects |
| Lead scoring | GPT-4o-mini scores 0–100 | No action taken; just a filter |
| Cold email + follow-ups | Sends up to 25/day, Day 3 + Day 7 | Rate-limited, unsubscribe respected, no money moves |
| Mockup generation | Static HTML created locally | No external calls except AI API |
| Mockup deploy | HTML pushed to Netlify | Free subdomain, no client-owned asset touched |
| Mockup delivery email | "Here's your free mockup" sent | Purely informational, no commitments made |
| Reply monitoring | IMAP poll, classify reply | Read-only until a positive match is confirmed |
| Cost logging | Token costs tracked in SQLite | Purely internal |

These steps can run on a cron schedule (`python -m src.orchestrator`) without Steele
being involved at all.

---

## Requires Steele's Input or Approval

| Step | What's Needed | Why |
|------|--------------|-----|
| **Close confirmation** | Steele reviews flagged positive reply and types `agree` | Before any money or domain purchase, Steele must confirm the deal is real. One bad "I guess so" from a confused prospect shouldn't trigger a $10 domain charge and hours of build work. |
| **Intake form completion** | Client must fill out the portal intake form | The agent can't fabricate logo, photos, brand colors, or real hours. These must come from the client. |
| **Deposit verification** | 50% deposit confirmed in portal | The agent checks the `deposits` table (or Stripe webhook), but Steele should verify for any amount > $0 before build starts. |
| **Photo/asset upload** | Client uploads via portal Projects tab | Agent can't source real photos — it uses placeholders until assets arrive. |
| **Domain selection** | Steele reviews suggested domain names | Namecheap will register whatever the agent suggests. A human should confirm the domain isn't embarrassing or wrong before $12 is spent. |
| **Final site review** | Steele does a visual QA of the built site | See "Should Involve Steele" below. |
| **DNS cutover** | Steele confirms DNS update | Pointing a domain to a new server is hard to undo quickly. Steele should confirm before this happens, especially if the client has an existing site. |
| **Question/neutral replies** | Steele reads and responds | The agent doesn't make up answers to client questions. These get flagged in the CRM with a `review_needed` flag. |

---

## Should Involve Steele (Even If Automatable)

These steps *could* be fully automated but involving Steele produces better outcomes
and protects his reputation:

### 1. Final site review before go-live
**Could automate**: Run Lighthouse, check links, verify forms.  
**Should involve Steele**: A broken button or wrong phone number goes live under *his*
brand. A 5-minute human review catches things automated tests miss (wrong logo,
embarrassing copy, photos on the wrong page). **Hard rule: Steele approves before DNS
points to the new site.**

### 2. Intake form review / client expectation setting
**Could automate**: Agent reads intake form and starts building immediately.  
**Should involve Steele**: The first time Steele reads a client's intake form is also
the time to spot red flags (unrealistic expectations, missing photos, brand colors that
will be ugly, etc.) before build work starts.

### 3. The first email to a booked prospect (post-Calendly)
**Could automate**: Send a templated "looking forward to our call" email.  
**Should involve Steele**: A short personal note from Steele before the call closes more
than a bot email. He already has the dossier — it takes 2 minutes.

### 4. Care plan upsell after go-live
**Could automate**: Send a templated care plan offer.  
**Should involve Steele**: A personal "how's the first week going?" call or message has
a much higher conversion rate than a bot sequence.

---

## Can the Agent Close via Email? (Without a Phone Call)

**Yes, under these specific conditions:**

1. Prospect explicitly says yes (e.g., "let's do it", "sounds good", "I want to move forward")
2. The mockup has been seen (status = `mockup_sent` before the reply)
3. No unresolved questions about price, timeline, or scope in the thread
4. Lead score ≥ 50 (not a marginal lead)
5. **Steele reviews the classified-positive reply before the build starts** (see above)

**No, the agent should NOT close without a phone call if:**
- The reply contains any question ("how long does it take?", "do you do X?")
- The reply is ambiguous ("maybe", "possibly", "sounds interesting")
- The lead score < 50
- The project is Top tier ($2,200) — at that price point, a call is worth it

**The agent's job in closing**: Classify the reply, update the status to `agreed_pending`,
and send Steele a Slack/email notification: "🟢 [Business Name] replied YES to their mockup.
Review and confirm at [portal link]." Steele clicks confirm in the portal, and the build
pipeline kicks off.

---

## Summary: Steele's Two Required Gates

```
GATE 1 — Before build starts
   Agent flags: "Lead agreed, intake form submitted, deposit received"
   Steele does: Reviews intake form, confirms domain, clicks "Start Build"
   Time: ~15 minutes per client

GATE 2 — Before go-live
   Agent flags: "Build complete, site ready for review at [preview URL]"
   Steele does: Visual QA, checks all links/forms/photos, clicks "Go Live"
   Time: ~10 minutes per client
```

Everything else — prospecting, scoring, outreach, follow-ups, mockup generation,
domain purchase, deployment, DNS, and client notification — is fully automated.

**Total Steele time per client: ~25 minutes of oversight on a $800–2,200 sale.**
