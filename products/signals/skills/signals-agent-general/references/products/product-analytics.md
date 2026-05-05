# Lens: Product analytics

The profile's `top_events` tells you which custom events define this team's
product surface. Anything beyond `$pageview`, `$autocapture`, `$identify`,
`$session_recording_*` is domain-specific — those are the events the product
team chose to instrument and care about. The profile's `popular_insights`
shows which behavioral metrics the team actively watches; movements on those
are visible to humans, so they're high-stakes.

This lens focuses on **behavioral patterns and metric movements** — distinct
from `web-analytics` (traffic / `$pageview`-shaped) and from `error-tracking`
(failure-shaped). When the team-defined events are healthy, the product is
likely healthy; when they shift, real product behavior changed.

## Quick scan from the profile alone

| Pattern                                                             | What it usually means                                                    |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Custom event `count` and `distinct_users` both stable across 7d/24h | Healthy baseline — no movement worth investigating                       |
| Custom event with `recent_24h_count / count` ≫ `1/7`                | Today's spike — new feature ship, marketing push, or breakage            |
| Custom event with `recent_24h_count / count` ≪ `1/7`                | Drop — broken instrumentation, deploy regression, or feature deprecation |
| `recent_24h_users` ≪ `recent_24h_count` (low users, high events)    | Loop or power-user — investigate per-user rate                           |
| `popular_insights` lists a metric; `query-trends` shows it moving   | Human-visible regression — the team will notice this                     |
| New event in `top_events` not present 7d ago                        | Fresh instrumentation; worth a memory entry, not a finding               |
| Event listed in `popular_insights` but `count = 0` in `top_events`  | Broken instrumentation — what humans watch isn't being captured          |

If a team's `top_events` is dominated by `$pageview` / `$autocapture` /
`$session_recording_*` and has very few domain events, they're using PostHog
for traffic analytics — pivot to the `web-analytics` lens.

## Patterns to look for

### Conversion-funnel regression

The team has `popular_insights` that include funnel-shaped metrics (e.g. signup
→ activation → first-action). `query-funnel` against the same series shows
conversion rate dropping below baseline (e.g. from 30% → 18% step-2-to-step-3).
Common causes: deploy regression breaking a step's UI, an experiment ramp,
upstream marketing change shifting cohort quality. Cross-source convergence
with `error-tracking` issues on the affected page or `activity-log-list` deploy
events is high-signal.

### Retention / stickiness drop

`query-retention` on a key user-action event shows D7 or D30 retention dropping
below the team's baseline. Or `query-stickiness` shows the active-user
distribution shifting toward fewer-active-days. Often a leading indicator of
churn before it shows up in revenue. Worth a finding only if the drop is
material (≥10% relative) and not explained by a normal seasonal cycle (memory
should record those — Mondays-vs-weekends, end-of-month, holidays).

### Custom-event spike (positive or negative)

A domain event jumps materially in volume vs baseline. `query-trends` with a
breakdown by `properties.<distinguishing-prop>` (often `feature`,
`environment`, or `source`) usually identifies the cause: a feature flag
flipped, an experiment ramped, a marketing campaign landed, or instrumentation
got duplicated. Memory entries should record expected-vs-unexpected spikes
with cadence — recurring weekend dips don't need re-emitting.

### Lifecycle composition shift

`query-lifecycle` shows new / returning / resurrecting / dormant proportions
changing. A drop in returning users with a rise in dormant is the classic
churn-early-warning shape. Combine with `query-retention` for confirmation.
Worth pairing with cohort filters before emitting — a shift driven entirely
by a recent marketing-acquired cohort is different from an organic shift.

### Cohort movement

Members of a known-important cohort (high-value users, recent signups, paying
customers) showing a behavior change visible in their event volume vs the
overall baseline. `query-trends` with a cohort filter is the cheapest read.
Memory should record which cohorts the team treats as load-bearing.

### Path / journey change

`query-paths` between two events that historically have a strong direct path
now shows a longer or different path. Often surfaces when a UX change inserts
new steps users have to navigate. High-signal when paired with a recent deploy
in `activity-log-list`. Use sparingly — paths queries are expensive and noisy
on large user bases; reach for it only with a concrete hypothesis.

## Disqualifiers

- **Self-traffic / dev / internal users** — most teams have internal users
  generating non-trivial event volume. Filter via `properties.email` domain
  match or a dedicated `internal` cohort. Memory should record what marker
  the team uses.
- **Bot / synthetic monitoring traffic** — automated traffic against
  production looks like users; check user-agents or distinct_id patterns.
- **Recent ship** — a custom-event spike right after a deploy is usually
  intentional rollout traffic, not a bug. Cross-check with
  `activity-log-list`. Worth a memory entry, not a finding.
- **Single-user spike on a low-volume event** — one engineer testing in
  production. Filter or pivot to per-user rate before weighing.
- **Demo / seeded events** — some teams have events like `posthog_test_*`
  or demo-fixture-driven names. Memory should record their patterns so
  future scouts skip them.
- **Seasonal dips** — weekend / holiday / end-of-month patterns recur. Once
  recorded, don't re-emit.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `query-trends` — the workhorse. Start here for any behavioral metric over
  time. Supports breakdowns, formulas, comparison-to-prior-period.
- `query-funnel` — conversion through a defined sequence. Use when the
  pattern smells like step drop-off.
- `query-retention` — D-N retention shapes. Use for cohort retention or
  feature retention.
- `query-lifecycle` — new / returning / resurrecting / dormant composition
  over time.
- `query-stickiness` — active-day distribution per user.
- `query-paths` — what users do before / after a key event. Expensive and
  noisy on large user bases — use only with a concrete hypothesis.
- `query-trends-actors` — pivot from "metric moved" to "which users moved
  it". Use after `query-trends` shows a shape worth drilling.
- `read-data-schema` — `events`, `event_properties`, `event_property_values`
  for confirming what's actually captured before constructing queries.
- `insight-get` / `insight-query` — pull existing team insights. The
  profile's `popular_insights` lists candidates; `insight-get` returns the
  saved query so you don't re-derive it.
- `cohorts-list` / `cohorts-retrieve` — find the team's defined user
  segments (paying, activated, churned). Filter behavioral queries by them.

For deep investigation playbooks, the sandbox image bakes
`posthog:investigate-metric` (root-cause analysis when a metric moves —
breakdowns, actors, paths, lifecycle, retention, annotations in sequence)
and `posthog:exploring-autocapture-events` (when CSS-selector-shaped
patterns appear in the autocapture surface). Lean on those rather than
re-deriving the investigation order.

## Memory shapes worth writing

After investigating product analytics on a project, leave durable steers like:

- _"This team's `signup` event runs ~200/day weekday, ~50/day weekend —
  weekend dips are normal seasonality, not signal."_ (`pattern`,
  `domain:product_analytics`, `entity:signup`)
- _"Funnel signup → activation runs 35% baseline; drops below 25% are worth
  flagging."_ (`pattern`, `domain:product_analytics`,
  `entity:signup_funnel`)
- _"The `internal` cohort accounts for ~12% of `feature_used` events —
  filter `properties.environment != 'internal'` for user-facing
  metrics."_ (`pattern`, `domain:product_analytics`,
  `entity:internal_filter`)
- _"D7 retention on `first_action` baseline is 45%; tracked in dashboard
  X."_ (`pattern`, `domain:product_analytics`,
  `entity:retention_baseline`)
- _"Demo seeded events: `posthog_test_\*` — skip when scanning custom
events."_ (`noise`, `domain:product_analytics`)

These compound: by run #5, the scout knows the team's healthy baselines, what
seasonality to expect, which segments to filter, and which insights humans
already watch. Findings narrow to genuine deviations.
