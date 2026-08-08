# Insight-hygiene scout: queries & rules

The sweep SQL, the query formats to parse, the exact mechanical rules, and worked examples.
The scenario-tested reference implementation is
`products/signals/backend/scout_harness/insight_hygiene.py`
(corpus: `products/signals/backend/test/test_insight_hygiene.py`) — keep this file and that
module saying the same thing; the corpus suite fails when they drift.

## §Sweep — pull every saved insight with its definition

Per the `execute-sql` contract, confirm the columns first — `system.*` column sets drift:

```sql
SELECT column_name, data_type
FROM system.information_schema.columns
WHERE table_name = 'system.insights'
ORDER BY column_name
```

Count form (quick close-out):

```sql
SELECT count()
FROM system.insights
WHERE saved = 1 AND deleted = 0
```

Sweep form (page through `last_modified_at DESC`, ~200 rows per run is plenty):

```sql
SELECT short_id, name, description, query, filters, last_modified_at, created_by_id, last_modified_by_id
FROM system.insights
WHERE saved = 1 AND deleted = 0
ORDER BY last_modified_at DESC
LIMIT 200
```

The tracked-event vocabulary for the stale-event check — events any insight's series references
(your positive-evidence set; fold it into `pattern:insight_hygiene:events` memory):

```sql
SELECT DISTINCT JSONExtractString(series.value, 'event') AS event
FROM system.insights
ARRAY JOIN JSONExtractArrayRaw(query, 'series') AS series
WHERE saved = 1 AND deleted = 0
  AND JSONExtractString(series.value, 'kind') = 'EventsNode'
  AND event != ''
```

human-renamed-vs-query-edited follow-up, per candidate (who touched it last, and what changed):
`insights-activity-retrieve` with the insight's `short_id` — look at the most recent activities:
a `name` change after the last `query`/`filters` change means the name is deliberate.

## Query formats

**New-style (`query` JSON)** — the trend-family kinds are `TrendsQuery`, `StickinessQuery`,
`LifecycleQuery`:

- window: `query.dateRange.date_from` (e.g. `-7d`, `-30d`, `-0mStart`; `null`/absent = the
  project default, treat as no contradiction; `"all"` = all time).
- series: `query.series[]` — `{kind: "EventsNode", event: "..."`, optional `name` for a display
  alias`}`, `{kind: "ActionsNode", id, name?}`. An ActionsNode tracks whatever the action
  definition captures — its `name` is the display label; use it for matching, never parse it
  apart. `DataWarehouseNode` series: judgment-only.
- breakdown: `query.breakdownFilter.breakdown` — a name claiming "by browser" with no
  `breakdownFilter` is judgment-confusing (report), not a mechanical check.

**Legacy (`filters` JSON, `query` empty)** — window: `filters.date_from`; series:
`filters.events[]` (`{name}`) + `filters.actions[]` (`{name}`).

**Out of mechanical scope** — `FunnelsQuery`, `RetentionQuery`, `PathsQuery`, `HogQLQuery`,
`InsightVizNode` wrapping any of those: verdicts there are judgment-only, report-only.

## Mechanical rules

### 1. Stale window

Extract the strongest date-range claim from name, then description (first match wins):

| Phrase shape                                   | Claim (`date_from` form)                        |
| ---------------------------------------------- | ----------------------------------------------- |
| "last/past N days", "N days", "14d / 7 d"      | `-Nd` (exact-day; rename-eligible)              |
| "last/past week·fortnight·month·quarter·year"  | `-1w` · `-2w` · `-1m` · `-1q` · `-1y`           |
| "last/past N weeks·months·quarters·years·hours" | `-Nw/m/q/y/h`                                   |
| "today", "this week·month·quarter·year"        | `-0dStart`, `-0wStart`, `-0mStart`, `-0qStart`, `-0yStart` |
| "daily/weekly/monthly/hourly" (+ users/usage)  | cadence claim — grain of the metric, NOT a window |

Rules:

- A claim that equals `date_from` (canonical form) → clean.
- A cadence claim is satisfied by any window **at least as long** (WAU over 90d is still WAU;
  WAU over `-1d` is stale — report, never rename).
- A claimed window on an all-time (`"all"`) insight is stale; an unclaimed window is clean.
- **Digit guard:** window claims need the day-unit glue ("days", "d") — bare digits never claim a
  window, and runs of 3+ digits are identifiers ("2024", "404 errors", "project 725"), not dates.
- **Rename-eligible** only for exact-day claims with an exact-day replacement: substitute the
  phrase, keep the rest of the title identical, e.g. `Pageviews (last 14 days)` +
  `date_from=-30d` → `Pageviews (last 30 days)`. `-Nw/-Nm/-Ny` replacements rephrase as
  "last M days" using 7/30/365-day conversion; `*Start`/ISO windows have no substitution → report.

### 2. Stale event

The name/description references a **known-tracked** event absent from the current series.
Event display forms: `$pageview` → "pageview(s)", "page view(s)"; `$exception` →
"exception(s)", "error(s)"; `$autocapture` → "autocapture(s)"; `$screen` →
"screenview(s)", "screen view(s)"; `$rageclick` → "rageclick(s)", "rage click(s)";
`$dead_click` → "deadclick(s)", "dead click(s)"; custom events: raw name, `$`-stripped, and
separators-to-spaces (`signed_up` → "signed up"). Longest phrase wins ("page views" before
"view"). The event must be in your positive-evidence set (this insight's own query or
`pattern:insight_hygiene:events` memory) — an unknown word never fires. **Always report-only:**
which event the insight is "about" after a swap is a human call.

### 3. Broken comparison

Name matches `A vs B` and the query holds fewer than two series. Report-only.

## Worked examples

| Name                          | Query                                | Verdict  | Action                                   |
| ----------------------------- | ------------------------------------ | -------- | ---------------------------------------- |
| Pageviews (last 14 days)      | -30d, `$pageview`                    | stale window | RENAME → "Pageviews (last 30 days)"  |
| All pageviews, last 7d        | -14d, `$pageview`                    | stale window | RENAME → "All pageviews, last 14d" (shorthand stays shorthand) |
| Pageviews (last 30 days)      | -30d, `$pageview`                    | clean    | —                                        |
| All pageviews, last 7d        | -7d, `$pageview`                     | clean    | —                                        |
| Pageviews (last 14 days)      | -2w, `$pageview`                     | clean (equivalent window) | —                 |
| Signups this month            | -7d, `signed_up`                     | stale window | report (no clean substitution)       |
| Weekly active users           | -90d                                 | clean (cadence satisfied) | —                          |
| Weekly active users           | -1d                                  | stale window | report (cadence can't hold)          |
| Clicks past week              | -2w, `$autocapture`                  | stale window | report                                   |
| Pageviews over time           | -14d, now `$autocapture`             | stale event (if `$pageview` previously sighted) | report |
| Pageviews over time           | -14d, `$autocapture`, no prior sighting | clean | —                                   |
| Signups vs logins             | 1 series                             | broken comparison | report                            |
| Signups vs logins             | 2 series                             | clean    | —                                        |
| Feature adoption 2024 stats   | -30d                                 | clean (2024 is an identifier) | —                  |
| 404 errors by page            | -14d, `$exception`                   | clean (404 is an identifier) | —                   |
| Key metrics                   | anything                             | clean (no claim) | —                                |
