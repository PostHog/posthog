# Insight-hygiene scout: queries and rules

This file holds the sweep SQL, the query formats to parse, the exact mechanical rules, and worked examples.
A scenario-tested Python reference implements the same rules at `products/signals/backend/scout_harness/insight_hygiene.py`.
The corpus lives in `products/signals/backend/test/test_insight_hygiene.py`. Keep this file and that module in sync. The corpus suite fails when they drift.

## §Sweep: pull every saved insight with its definition

Per the `execute-sql` contract, confirm the columns first. `system.*` column sets drift:

```sql
SELECT column_name, data_type
FROM system.information_schema.columns
WHERE table_name = 'system.insights'
ORDER BY column_name
```

Count form (for the quick close-out):

```sql
SELECT count()
FROM system.insights
WHERE saved = 1 AND deleted = 0
```

Sweep form. Page through rows in `last_modified_at DESC` order. ~200 rows per run is plenty.
Select the numeric `id` as well: `insights-activity-retrieve` only accepts a numeric id. Pass
that, never `short_id`, when you pull an insight's edit history.

```sql
SELECT id, short_id, name, description, query, filters, last_modified_at, created_by_id, last_modified_by_id
FROM system.insights
WHERE saved = 1 AND deleted = 0
ORDER BY last_modified_at DESC
LIMIT 200
```

When the sweep returns the full 200 rows, the run has not seen the whole population. Filter the
next run with `AND last_modified_at < {oldest last_modified_at you scored this run}` and keep
walking. Record how far you got in `pattern:insight_hygiene:baseline` (covered through
{timestamp}). The quick close-out only applies once the baseline says the full population was
covered. Until then, every run must make progress, even when nothing changed recently.

The tracked-event vocabulary: every event any insight's series references. Use it for one job
only: mapping a title word to a possible event name (the display-form dictionary). It is NOT
evidence for a stale-event verdict. A stale event fires only on per-insight evidence: you once
saw the event in THIS insight's own series (its current query, or the series list in its
`dedupe:` entry). "Pageviews" on an insight that always tracked `$autocapture` is a naming
choice, even when other insights in the project track `$pageview`.

Saved insight queries are persisted wrapped (`{"kind": "InsightVizNode", "source": {...}}`),
so read series from `query.source`, falling back to the bare node for unwrapped rows:

```sql
SELECT DISTINCT JSONExtractString(series, 'event') AS event
FROM system.insights
ARRAY JOIN JSONExtractArrayRaw(coalesce(nullIf(JSONExtractRaw(query, 'source'), ''), JSONExtractRaw(query)), 'series') AS series
WHERE saved = 1 AND deleted = 0
  AND JSONExtractString(series, 'kind') = 'EventsNode'
  AND event != ''
```

Fold the list into `pattern:insight_hygiene:events` memory as the recognition dictionary.

For the human-renamed-vs-query-edited check on a candidate, call `insights-activity-retrieve`
with the insight's numeric `id` from the sweep row (the tool does not accept `short_id`). Read
the most recent activities. A `name` change after the last `query` or `filters` change means
the name is deliberate.

## Query formats

**New-style (`query` JSON).** The API persists ordinary saved trend-family queries wrapped:
`{"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", ...}}`. Unwrap `query.source`
first. Older rows can hold the bare kind directly. The supported trend-family kinds are
`TrendsQuery`, `StickinessQuery`, and `LifecycleQuery`:

- Window: `source.dateRange.date_from` (e.g. `-7d`, `-30d`, `-0mStart`). Absent or `null` means the project default: treat it as no contradiction. `"all"` means all time.
- Series: `source.series[]`. An `EventsNode` entry has an `event` field and an optional `name` display alias. An `ActionsNode` entry has an `id` and an optional `name` display label; the name is what you match against, never parse it. A `DataWarehouseNode` series is judgment-only.
- Breakdown: `source.breakdownFilter.breakdown`. A name claiming "by browser" on a query with no `breakdownFilter` is judgment-confusing: report it. This is not a mechanical check.
- An `InsightVizNode` whose source kind is out of scope (funnels, retention, paths) is judgment-only, like an unwrapped one.

**Legacy (`filters` JSON, `query` empty).** Window: `filters.date_from`. Series: `filters.events[]` (each has a `name`) plus `filters.actions[]` (each has a `name`).

**Out of mechanical scope.** `FunnelsQuery`, `RetentionQuery`, `PathsQuery`, `HogQLQuery`, and any `InsightVizNode` that wraps those kinds get judgment-only verdicts and report-only actions.

## Mechanical rules

### 1. Stale window

Extract the strongest date-range claim from the name, then from the description. First match wins:

| Phrase shape                                   | Claim (`date_from` form)                        |
| ---------------------------------------------- | ----------------------------------------------- |
| "last/past N days", "N days", "14d / 7 d"      | `-Nd` (exact-day; substitution-eligible)       |
| "last/past week·fortnight·month·quarter·year"  | `-1w` · `-2w` · `-1m` · `-1q` · `-1y`           |
| "last/past N weeks·months·quarters·years·hours" | `-Nw/m/q/y/h`                                   |
| "today", "this week·month·quarter·year"        | `-0dStart`, `-0wStart`, `-0mStart`, `-0qStart`, `-0yStart` |
| "daily/weekly/monthly/hourly" (+ users/usage)  | cadence claim: the metric's grain, NOT a window |

Rules:

- A claim that equals `date_from` (in canonical form) is clean.
- Compare windows symbolically, not by string: `-2w` and "last 14 days" are the same window. Day equivalences: `w=7`, `m=30`, `y=365`. This mapping is fixed on purpose; a calendar-aware comparison would flip verdicts month to month.
- A cadence claim is satisfied by any window **at least as long**. WAU over 90 days is still WAU. WAU over one day is stale: report it. No mechanical substitution exists for cadence names, so the fix column names the mismatch instead.
- A claimed window on an all-time (`"all"`) insight is stale.
- **Digit guard.** A window claim needs day-unit glue ("days" or "d"). Bare digits never claim a window. Runs of 3+ digits are identifiers ("2024", "404 errors", "project 725"), not dates.
- **Rename-eligible** only for exact-day claims with an exact-day replacement. The scout never applies the rename. It prints the substitution as the suggested fix in the report, and the human applies it with one edit. Substitute the phrase and keep the rest of the title identical. Example: `Pageviews (last 14 days)` + `date_from=-30d` → suggested fix "Rename to `Pageviews (last 30 days)`". Keep the shorthand style: `All pageviews, last 7d` + `-14d` → "Rename to `All pageviews, last 14d`". `-Nw`, `-Nm`, and `-Ny` replacements rephrase as "last M days" using the fixed day equivalences. `*Start`, ISO, and all-time windows have no substitution: the fix column describes the mismatch instead.

### 2. Stale event

The name or description references an event absent from this insight's current series.
Event display forms: `$pageview` → "pageview(s)", "page view(s)"; `$exception` → "exception(s)", "error(s)"; `$autocapture` → "autocapture(s)"; `$screen` → "screenview(s)", "screen view(s)"; `$rageclick` → "rageclick(s)", "rage click(s)"; `$dead_click` → "deadclick(s)", "dead click(s)".
Custom events use three forms: the raw name, the `$`-stripped name, and the separators-to-spaces form (`signed_up` → "signed up").
Longest phrase wins: "page views" beats "view".

Fire only with PER-INSIGHT evidence: you positively saw the event in THIS insight's series. Two
sources: the insight's own current query (a drop added but the event still present means no
fire), or its `dedupe:` entry (each entry records the series events you scored). The project-
wide vocabulary query above is only the display-form recognition dictionary. An insight titled
"Pageviews" that always tracked `$autocapture` never fires, regardless of what other insights
track. An unknown word never fires.
**Always report-only.** Which event the insight is "about" after a swap is a human call.

### 3. Broken comparison

The name matches `A vs B` and the query holds fewer than two series. Report-only.

## Worked examples

| Name                          | Query                                | Verdict  | Fix column in the report                  |
| ----------------------------- | ------------------------------------ | -------- | ---------------------------------------- |
| Pageviews (last 14 days)      | -30d, `$pageview`                    | stale window | "Rename to `Pageviews (last 30 days)`"  |
| All pageviews, last 7d        | -14d, `$pageview`                    | stale window | "Rename to `All pageviews, last 14d`" (shorthand stays shorthand) |
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
