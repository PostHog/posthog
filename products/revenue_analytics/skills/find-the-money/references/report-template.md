# Report template

The skill writes exactly one file: `./find-the-money-{YYYY-MM-DD}.md`. If a same-
date report already exists, overwrite and tell the user.

## Standard report

````markdown
# Find the money — {project name} — {YYYY-MM-DD}

**Window:** {N} days **Focus:** {grow / expand / save / all}
**Buyer unit:** {person / org} **Revenue signal:** {event / warehouse / both}

## TL;DR

1. **{Top opportunity}** — {one-sentence framing}. See §1.
2. **{Second opportunity}** — {one-sentence framing}. See §2.
3. **{Third opportunity}** — {one-sentence framing}. See §3.

---

## 1. {Opportunity title} — high confidence

**Why this matters**
{One sentence on the business mechanism. Why does this move revenue?}

**Evidence**

- {Key number from the query — e.g. "247 users, 11% of paid base"}
- {Comparator — vs. median, vs. base rate, vs. prior period}
- {Link to PostHog page — cohort filter URL, web analytics, or insight if applicable}
- See appendix §A.{n} for the HogQL.

**Recommended actions**

- [ ] Create a cohort: {exact filter description so the user can build it}
- [ ] {Campaign / outreach / experiment to run}
- [ ] {Instrumentation gap to close, if any}
- [ ] {Optional: dashboard to monitor going forward}

**Watch out for**
{Any caveat — small n, selection effects, seasonality. One line max.}

---

## 2. {Opportunity title} — high confidence

{same structure}

---

## 3. {Opportunity title} — medium confidence

{same structure}

---

(...up to ~8 opportunities total; high → medium → low)

---

## Data gaps

Things we couldn't measure and why:

- **{Gap}** — {missing event / property / source}. To unlock, instrument
  `{event_name}` with property `{prop_name}`, or connect a {Stripe / Chargebee /
  etc.} source via the data warehouse.
- ...

## Appendix — queries

### §A.1 — {analysis name}

```sql
{the actual HogQL run, with substitutions resolved}
```

Result summary: {one-line key number}

### §A.2 — {analysis name}

```sql
...
```

(... one entry per analysis run)
````

## "Instrument this first" report (no signal)

Use when the project has no detectable revenue signal — no `$revenue` property, no
billing warehouse source, no plan property.

```markdown
# Find the money — {project name} — {YYYY-MM-DD}

## We can't find revenue in this project yet

To run a revenue audit, PostHog needs at least one of:

1. **A revenue event** — e.g. `purchase`, `subscription_created`, with a numeric
   `$revenue` or `amount` property. Use `posthog.capture('purchase', { $revenue: 19.99 })`.
2. **A billing warehouse source** — connect Stripe, Chargebee, or Shopify under
   Data warehouse → Sources. Tables like `stripe_charges`, `stripe_subscriptions`
   become queryable.
3. **A plan / tier person property** — `posthog.identify(id, { plan: 'pro' })` lets
   us segment users by tier even without revenue events.

## Recommended first move

{Based on the project's existing instrumentation, recommend the cheapest path:

- if PostHog SDK is installed and events are flowing → instrument a revenue event
- if there's a known payment provider mentioned in the wizard → suggest the warehouse source
- if neither → instrument the SDK first}

## What we'd unlock

Once you have a revenue signal, re-run `/find-the-money` and we'll surface:

- Top-decile revenue concentration
- High-ROI acquisition channels
- Upsell candidates inside lower tiers
- Dormant paid users at churn risk
- Time-to-value gaps by segment
```

## Formatting rules

- Use markdown checkboxes (`- [ ]`) for action items so the file works as a working
  document the user can tick off.
- Inline-link PostHog pages with relative paths: `[Cohort](/cohorts/new?filters=...)`.
- Keep "Why this matters" to one sentence. The user is busy.
- Keep "Watch out for" to one line. If a caveat is bigger than that, downgrade the
  confidence band instead.
- Confidence band shows in the section heading (`— high confidence`,
  `— medium confidence`, `— low confidence`). No emojis.
- Cap the report at ~8 opportunities. More than that, the user stops reading and
  the report stops being actionable.
