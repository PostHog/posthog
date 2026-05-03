# Lens: web analytics

Web analytics signals live in `top_events` (`$pageview`, `$autocapture`,
`$screen`, `$session_started`) and ripple through `popular_insights` and
`recent_dashboards`. The `count` / `distinct_users` shape over the recent
window is what tells the scout whether traffic is healthy, surging, or
regressing.

## Quick scan from the profile alone

Look at web events in `top_events` and the dashboards / insights that depend
on them:

| Pattern                                                                   | What it usually means                       |
| ------------------------------------------------------------------------- | ------------------------------------------- |
| `$pageview` `count` and `distinct_users` rising together in 24h           | Real traffic surge — campaign / launch      |
| `$pageview` `count` rising but `distinct_users` flat                      | Bot / crawler / single user looping         |
| `$pageview` dropped sharply in 24h vs 7d baseline                         | Deploy regression or instrumentation break  |
| `$autocapture` events present but `$pageview` absent                      | SPA route-change tracking only — confirm    |
| New top entry in `top_events` (recent first_seen)                         | Fresh autocapture pattern — release marker  |
| `$session_started` rising while `$pageview` flat                          | Session-id churn — cookie issue suspected   |
| `popular_insights` lists a funnel that hasn't been viewed since the spike | Funnel may be broken — nobody's checking it |

If web events are quiet across the board and no popular insight is
funnel-shaped, web analytics probably isn't where the signal is today.

## Patterns to look for

### Pageview burst with broad reach

`recent_24h_count` and `recent_24h_users` both elevated. Validate with
`query-trends` on `$pageview` over 30 days to confirm it's not a recurring
weekly pattern (Monday surge, weekly newsletter). If genuinely fresh, drill
into top referrers / campaigns:

1. `read-data-schema event_property_values` for `$current_url`, `$referrer`,
   `utm_source`, `utm_campaign`.
2. `query-trends` with breakdown by referrer or `utm_campaign` over the burst
   window.
3. Cross-check `recent_dashboards` — if a marketing dashboard was viewed
   heavily during the burst, the team is already aware; lower the weight of
   the emit.

### Pageview drop / instrumentation regression

`recent_24h_count` materially below the 7d-prior baseline (≥ 30% drop) without
a corresponding `distinct_users` drop. Common causes: a new deploy broke the
SDK init path, a CSP change blocked the script, an A/B test misrouted users
to a non-instrumented variant.

`activity-log-list` for recent deploys + `read-data-schema event_properties`
on `$pageview` to see if `$lib_version` shifted. Cross-source convergence
with `error-tracking-issues-list` (search for SDK-init exceptions) is high-
signal.

### Conversion funnel drop

`popular_insights` shows a funnel near the top. Run `insight-get` to inspect
its definition, then `query-funnel` over the recent window vs the prior week.
If a step's conversion rate dropped materially, surface it. Pair with
`activity-log-list` to correlate with releases on the page involved.

### New autocapture surface

`top_events` shows an autocapture event with `first_seen` in the last few
days that has high volume. Often a new CSS class on a freshly deployed page
— sometimes a regression where every element on a page started capturing.
Pull a few raw events via `read-data-schema event_property_values` on
`$elements_chain` / `$el_text` to see what's firing.

### Session length / bounce anomaly

`$session_started` count vs `$pageview` count tells you average pages-per-
session. If pages-per-session collapses (sessions are shorter), users are
bouncing — usually a UX regression or a page that's load-broken. Validate
via `query-stickiness` on `$pageview` per session.

## Disqualifiers (skip these)

- **Weekend dips** — most consumer web products see ~30% drop weekend vs
  weekday. If memory doesn't already record this, leave a memory entry; do
  not emit.
- **Bot / crawler traffic spikes** — `count` ≫ `distinct_users` and
  user-agent skewed to bot strings. Filter on `properties.$lib =
'web'` and bot detection if available.
- **Marketing campaign launches** — calendar-driven, recurring. Memory
  should record the cadence; cross-check before emitting.
- **A/B test variant traffic shifts** — when an experiment ramps, the variant
  pageview volume shifts intentionally. Cross-check with `experiment-list`
  before treating as a finding.
- **`localhost` / `dev` / `staging` traffic** — filter on `$host` or the
  team's `app_urls` from `project_context` before weighing.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `query-trends` — primary tool for traffic shape over time, breakdowns,
  comparison windows.
- `query-funnel` — for conversion funnels surfaced by `popular_insights`.
- `query-paths` — for "what do users do after / before X" questions when a
  burst lands on a specific page.
- `query-retention` / `query-stickiness` — for session-quality anomalies.
- `query-lifecycle` — for new vs returning vs dormant composition shifts.
- `read-data-schema events / event_properties / event_property_values` —
  always-on for confirming an event / property / value exists before querying.
- `web-analytics-weekly-digest` — pre-computed weekly digest if available;
  cheap baseline.
- `insight-get` — drill into a popular insight's definition before querying it
  yourself.

For deep investigation playbooks, the sandbox image bakes
`posthog:investigate-metric` (root-cause analysis on any metric change —
breakdown / actor / path / lifecycle / annotation orchestration),
`posthog:exploring-autocapture-events` (CSS selectors, autocapture taxonomy,
elements_chain queries), and `posthog:querying-posthog-data` (HogQL syntax,
system tables, schema-discovery workflow).

## Memory shapes worth writing

After investigating web analytics on a project, leave durable steers like:

- _"`$pageview` baseline is ~12k/day across ~7k users; weekend dips of ~30%
  are normal."_ (`pattern`, `domain:web_analytics`)
- _"Marketing campaign 'spring-2026' runs every Tue/Thu — pageview spikes
  those mornings are expected."_ (`pattern`, `domain:web_analytics`,
  `entity:spring-2026`)
- _"SDK was upgraded to posthog-js 1.220 on 2026-04-28 — any SDK-init
  exceptions before that date are old."_ (`addressed`,
  `domain:web_analytics`)
- _"Funnel `signup-conversion` (insight 1342) is the team's primary KPI —
  surface drops > 5% sustained over 3 days."_ (`pattern`,
  `domain:web_analytics`, `entity:signup-conversion`)

These compound: by run #5, the scout has the team's traffic rhythm, knows
which campaigns are recurring, and only surfaces genuine regressions.
