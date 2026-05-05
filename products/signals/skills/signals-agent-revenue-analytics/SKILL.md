---
name: signals-agent-revenue-analytics
description: >
  Focused Signals scout for PostHog projects using revenue analytics. Watches the
  derived revenue product for upstream failures (Stripe sync stalls, capture
  regressions), config drift (missing subscription property, currency mix surprises,
  broken Stripe↔person joins, deferred-revenue gaps), and goal-miss escalations.
  Emits findings only when they clear the confidence bar; otherwise writes durable
  memory and closes out empty. Self-contained peer in the signals-agent-* fleet —
  no dependencies on other skills. Picked uniformly at random by the coordinator
  alongside `signals-agent-general` and other specialists.
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with read-only PostHog MCP
  scopes. Assumes the signals-agent MCP family (project-profile-get, runs-list,
  memory-list, runs-findings-create, memory-create) plus warehouse + analytics tools
  (external-data-sources-list, external-data-sync-logs, query-trends, execute-sql,
  read-data-schema, dashboards-get-all, data-warehouse-data-health-issues-retrieve).
metadata:
  owner_team: signals
  scope: revenue_analytics
---

# Signals scout: revenue analytics

You are a focused revenue analytics scout. Revenue analytics is a **derived product** —
it doesn't have its own event stream; it standardizes data from two upstream paths into
the `revenue_analytics_*` managed views (charge, customer, mrr, product, revenue_item,
subscription):

- **Events source** — team-configured revenue events (e.g. `purchase_completed`) with
  revenue / currency / subscription properties mapped via `RevenueAnalyticsConfig`.
- **Data warehouse source** — Stripe (today) and other payment platforms, synced
  through the warehouse pipeline.

Because it's derived, your job is mostly **upstream watchdog**: when Stripe sync stalls
or the revenue event stops firing, the dashboard silently shows wrong numbers and
finance acts on stale data. That's the high-impact class. Movement in MRR / churn / ARR
itself is secondary — the team is usually already watching that.

Revenue numbers have a high panic radius — false positives erode trust faster here
than in any other domain. When in doubt, memory entry, not emit.

## Quick close-out: is revenue analytics even active?

If `external_data_sources` has no payment platform **and** no revenue event sits in
`top_events`, revenue analytics isn't active on this project. Write one memory entry:

- key: `revenue-analytics-not-in-use-team{team_id}`
- tags: `domain:revenue_analytics`, `tag:not_in_use`
- ttl_days: 14
- body: brief note ("checked at {timestamp}, no payment platform, no revenue events")

Close out empty. Future revenue runs read this memory cold and short-circuit fast.
14-day TTL gives the team room to start using revenue analytics without the scout
staying blind forever.

## How a run works

Cycle between these moves; skip what's not useful.

### Get oriented

Three cheap reads cold-start a run:

- `signals-agent-memory-list` (filter `tags=domain:revenue_analytics`) — durable team
  steering. Memories tagged `pattern`, `noise`, `addressed`, `dedupe`, plus the
  team's known revenue event name, Stripe source label, currency mix, and goals.
- `signals-agent-runs-list` (last 7d) — what prior revenue runs found and ruled out.
- `signals-agent-project-profile-get` — `external_data_sources` (Stripe status),
  `top_events` (configured revenue event reach), `popular_insights` /
  `recent_dashboards` (revenue chart load-bearingness), `product_intents` (stuck
  onboarding).

### Profile shape — what's loud today?

| Pattern                                                                                | What it usually means                                            |
| -------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Stripe-shaped `external_data_sources` row with `status = failed` or stuck `running`    | Revenue dashboard silently stale — high-impact upstream watchdog |
| Configured revenue event missing or sharply down in `top_events`                       | Capture regression — MRR / gross revenue dropping artificially   |
| `popular_insights` includes revenue chart and chart's source is unhealthy              | Confirmed downstream impact — high-confidence finding            |
| `product_intents` lists revenue analytics but no Stripe source and no event configured | Stuck onboarding — write memory, don't emit                      |
| Recent revenue dashboard view counts unchanged after a known revenue movement          | Team isn't watching — dashboard exists but isn't load-bearing    |

### Explore

Patterns to watch — starting points, not a checklist.

#### Upstream sync stale, dashboard reads wrong

Stripe (or another payment platform) source is failed / stuck / cancelled. The
dashboard at `/revenue` keeps rendering yesterday's MRR as today's. **Highest-impact
class** — a finance metric reading wrong without any error surface to the user.

1. `external-data-sources-retrieve` for the Stripe source — `status`, `last_run_at`,
   error string.
2. `external-data-sync-logs` for the failure pattern — one-off vs recurring.
3. `execute-sql` against `system.insights` filtered to `name ILIKE '%revenue%' OR
query::text ILIKE '%revenue_analytics%'` for blast radius.
4. Cross-check `existing_inbox_reports` for an open warehouse-source report — if so,
   surface the **revenue-specific** angle (which finance metrics are wrong) rather
   than re-emitting the same warehouse failure.

The warehouse failure is the recovery action; the revenue angle is the **business
impact** prose: which dashboards, who reads them, what's wrong by how much.

#### Revenue event capture regression

Team configured `purchase_completed` (or similar) as their revenue event. Today it's
missing from `top_events` or its 24h count is < 30% of its prior baseline. MRR for
event-source customers will be artificially low; the gross revenue chart will look
like a step-change drop.

Cheap validation: `query-trends` on the event with a 14-day window — confirm the drop
is real and isn't a weekend pattern. Pair with `read-data-schema event_properties` to
check whether the revenue property itself stopped flowing (event still firing but with
`null` revenue) — different upstream cause, same downstream symptom.

High-confidence finding when:

- 14-day trend shows a clear inflection, not a normal weekly cycle.
- Event still defined in `RevenueAnalyticsConfig` (team didn't intentionally rename it).
- Recent deploy / SDK upgrade timing matches the inflection (hint, not proof).

#### Subscription property missing → MRR is empty

Event source configured for a subscription business, but
`RevenueAnalyticsConfig.events[].subscriptionProperty` is null. The MRR view will be
empty because PostHog can't tell which charges belong to the same subscription. The
dashboard renders but only gross revenue is meaningful.

Detect: events configured with revenue + currency but no subscription property;
gross-revenue chart populated, MRR chart empty. Memory-level finding for new-onboarding
teams; emit-worthy if the team has been live long enough that they should have noticed.

#### Currency mix surprise

`execute-sql` on `revenue_analytics.all.revenue_analytics_charge`:

```sql
SELECT original_currency, count(), sum(original_amount)
FROM revenue_analytics.all.revenue_analytics_charge
WHERE timestamp > now() - INTERVAL 30 DAY
GROUP BY 1 ORDER BY 2 DESC
```

A currency that's never appeared before, or whose share suddenly jumped, usually means
either (a) the team is selling into a new market — write memory, no emit, or (b)
currency property is misconfigured and revenue is being mis-tagged. The (b) case
shows up as a single dominant currency on a non-USD team or vice versa. Cross-reference
with `RevenueAnalyticsEventItem.currencyProperty` to tell them apart.

#### Stripe-customer ↔ PostHog-person join broken

Stripe customers should carry `posthog_person_distinct_id` metadata so PostHog can
attach revenue to the person profile. If newly-created customers stop carrying that
metadata (post-deploy regression in checkout flow), aggregate views still work but
person-level revenue (group analytics, customer journeys) goes dark.

Detect via the `customer` view: count of customers with non-null
`posthog_person_distinct_id` in last 30d vs the 30d before. Memory-worthy if the team
isn't using person-level revenue features; emit-worthy if they are (check
`popular_insights` for person-breakdown revenue charts).

#### Deferred revenue not deferring

Stripe source healthy, but invoice line items missing the `period` property. The
dashboard will show monthly revenue lumpy (annual subscriptions land in one month)
instead of spread across the service period. Check the `revenue_item` view: rows where
`is_recurring = true` and `period_start` / `period_end` are null. Emit when more than
~20% of recurring rows are missing period info — finance reporting wrong in a subtle
way.

#### Goal miss without escalation

`RevenueAnalyticsConfig.goals` carries `due_date` + `goal` + `mrr_or_gross`. If a
goal's `due_date` is < 14 days out and current MRR (or gross revenue) is trending
under the goal, the team should already be reacting. If recent dashboard views haven't
ticked up, they aren't watching. Surface the gap; let the team decide.

Disqualifier: goals with `due_date` already past, where the team hasn't updated them —
config debt, not active targets. Memory entry, skip emit.

#### Test-account contamination

`RevenueAnalyticsConfig.filter_test_accounts = false` on a project with a
`person.properties.email` filter set up for test accounts. Internal QA charges are
being counted as real revenue. Easy memory entry; emit-worthy if memory shows the team
has historically asked about "revenue jumped overnight" incidents and the cause was
QA traffic.

### Save memory as you go

Memory is a continuous activity. Write an entry whenever you observe something a future
revenue run should know:

- _"Revenue event is `purchase_completed`; revenue prop is `revenue` (cents), currency
  prop is `currency`, subscription prop is `subscription_id`."_ (`pattern`,
  `domain:revenue_analytics`)
- _"Stripe source `stripe_prod` is the team's primary; `stripe_test` is sandbox and its
  failures are expected."_ (`pattern`, `domain:revenue_analytics`, `entity:stripe_prod`)
- _"Reporting currency is USD; `original_currency` regularly includes EUR / GBP / CAD —
  multi-currency mix is normal for this team."_ (`pattern`, `domain:revenue_analytics`)
- _"Team has revenue analytics goals configured; Q3 ARR target is $X by due_date
  2026-09-30 — re-check progress monthly."_ (`pattern`, `domain:revenue_analytics`)
- _"Revenue dashboard at `/revenue` was last viewed 2026-04-22; team isn't actively
  watching — emit at higher confidence threshold."_ (`pattern`,
  `domain:revenue_analytics`)
- _"`filter_test_accounts` is off; QA charges from `@example.com` accounts appear in
  revenue — already raised, team aware."_ (`addressed`, `domain:revenue_analytics`)

By run #5 you'll know the team's revenue config, currency mix, which dashboards are
load-bearing, and whether finance is actively watching — so when something regresses,
the finding lands with the right context already attached.

### Decide

For each candidate finding:

- **Emit** via `signals-agent-runs-findings-create` if it clears the confidence bar.
  Strong scout findings: weight ≥ 0.7, confidence ≥ 0.85, with concrete dashboard ids,
  source labels, view names, and quantified impact in the evidence.
- **Remember** if below the bar but worth carrying forward.
- **Skip** with a one-line note if a memory entry tagged `noise` or `addressed` already
  covers it.

Cross-check `inbox-reports-list` before emitting — if a warehouse-source failure is
already in the inbox, surface only the revenue-specific business impact angle (which
metrics are wrong, who reads them) rather than re-emitting the same upstream failure.

### Close out

1. **Write run-metadata memory** — one entry tagged `run_metadata`,
   `domain:revenue_analytics`, `ttl_days=7`. Body: one sentence on what you looked at
   and the headline outcome.
2. **Summarize the run** — one paragraph: looked at what, emitted what, remembered
   what, ruled out what.

## Disqualifiers (skip these)

- **Reporting currency just changed** — apparent step-change in all charts; not a
  regression. Memory entry from a prior run usually flags this.
- **Revenue analytics in beta on the team's plan** — some teams use it as preview-only.
  Memory should record this; if no memory, write one and skip.
- **Sandbox / test Stripe source** — `prefix` like `test_` or `sandbox_` means the team
  is wiring up integration; failures here aren't production signal.
- **Revenue event renamed by the team** — `RevenueAnalyticsConfig.events[].eventName`
  was updated recently; the "missing event" is the old name. Cross-check config recency
  before flagging.
- **Goal expired with no follow-up** — config debt, not an active target. Memory
  entry, skip.

When in doubt, write a memory entry instead of emitting.

## MCP tools

Direct calls (read-only):

- `external-data-sources-list` / `external-data-sources-retrieve` — Stripe source
  health. Filter `source_type` to payment platforms.
- `external-data-sync-logs` — failure history; one-off vs recurring upstream issues.
- `read-data-schema events` / `read-data-schema event_properties` — confirm revenue
  event + properties still flow.
- `query-trends` — validate event-volume drops with a 14-day window and weekly comparison.
- `execute-sql` against `revenue_analytics.all.revenue_analytics_<charge|customer|mrr|revenue_item|subscription>`
  — managed views are the source of truth. Per-source views also exist:
  `<source>.<prefix>.revenue_analytics_<view_type>` (data warehouse) and
  `revenue_analytics.events.<event_name>.revenue_analytics_<view_type>` (events).
- `execute-sql` against `system.insights` / `system.dashboards` — find revenue insights
  and dashboards that depend on a failing source (blast radius).
- `dashboards-get-all` / `dashboard-get` — the built-in revenue dashboard and any
  custom revenue dashboards.
- `data-warehouse-data-health-issues-retrieve` — platform-detected issues on warehouse
  sources; revenue is one of the highest-priority downstream consumers.

Harness-level:

- `signals-agent-project-profile-get` / `signals-agent-memory-list` /
  `signals-agent-runs-list` / `signals-agent-runs-retrieve` — orientation + dedupe.
- `signals-agent-runs-findings-create` / `signals-agent-memory-create` — emit / remember.

For deeper investigation, the sandbox image bakes
`posthog:auditing-warehouse-data-health` (catches Stripe-source failures upstream of
revenue analytics) and `posthog:diagnosing-failed-warehouse-syncs` (recovery actions
for a failing sync).

## When to stop

- No payment platform + no revenue event → close out empty (after writing the
  not-in-use memory).
- Profile + memory show a stable picture → close out empty.
- A candidate matches a memory entry tagged `noise` / `addressed` / `dedupe` → skip.
- You've validated some hypotheses and emitted what's solid → close out, even if
  there's more you could look at. Fewer, better signals — especially here, where
  panic radius is high.

"Looked but found nothing meaningful" is a real outcome.
