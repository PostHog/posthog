Compare the log patterns of two time windows and return what changed: templates that are **new**, templates whose rate **shifted** (with magnitude, e.g. 4x), and templates that are **gone**. This is the single most useful call for incident triage — "what is different about now vs. before it broke" in one round trip, instead of mining two windows yourself and hand-matching templates.

All parameters must be nested inside a `query` object, with an optional sibling `baselineDateRange`.

# When to use

- **Incident triage (the primary loop):** set `query.dateRange` to the incident window. Omit `baselineDateRange` (defaults to the same window one week earlier) or set it to a known-good window just before the incident. The `new` and biggest `rate_shift` entries are your suspects; pivot to their raw lines with `query-logs`.
- **Explain a spike:** when a count or sparkline shows a spike (e.g. from `logs-count-ranges`), set `query.dateRange` to the spike window and `baselineDateRange` to the window just before it — the top `new` and `rate_shift` entries are the explanation. This is one call; do not mine the two windows separately and diff them yourself.
- **Post-deploy check:** current window = since the deploy; `baselineDateRange` = the same-length window just before it. New error-severity templates right after a deploy are the classic regression signature.
- **"What changed this week?"** — current = `-1d`, baseline auto. Good periodic sweep for a service you own.

## Pick the right tool

- Just summarize one window's content → `logs-patterns`.
- Explain a _count_ change without needing message content → `logs-count-ranges` (cheaper).
- Use **this** tool when you need to know _which messages_ are new or behaving differently between two periods.

# Reading the response

Entries come sorted most-interesting-first: `new` (by volume), then `rate_shift` (by magnitude), then `gone`, then `unchanged`.

- `classification` — trust the labels; the thresholds already handle sampling honesty:
  - `new` requires clearing a novelty floor (~1% volume share, or any error/fatal lines). Below the floor, absence from the baseline sample is not evidence of novelty.
  - `rate_shift` requires ≥2x change in per-second rate (windows of different lengths are normalized) _and_ enough raw samples on both sides.
  - `unchanged` means "no confident claim", not "provably identical".
- `rate_ratio` — current rate / baseline rate. 4.0 = 4x faster now, 0.25 = quartered.
- `pattern` — full pattern stats including `match_regex` / `match_literal`, so you can pivot straight to the matching lines (same recipe as `logs-patterns`: message regex filter + the pattern's services/severities).
- **Check `baseline.total_count` before trusting a wall of `new` entries** — an empty or tiny baseline (logging only started recently, service didn't exist last week) makes everything look new.
- Both windows are mined from samples (`sampled: true`), so counts are estimates and templates rarer than ~1 in 10,000 rows may be invisible in either window.

Template identity across the two windows is fingerprint-based (literal content), so the miner rendering `User <*> not found` in one window and `User <num> not found` in the other still compares as one pattern rather than a false new+gone pair.

# Parameters

## query.dateRange

The current (foreground) window — the period you are investigating. Same format as `logs-patterns`.

## baselineDateRange

Optional, sibling of `query` (not inside it). The comparison window. Omit for the default: the current window shifted back exactly one week, which absorbs daily/weekly volume cycles. Provide explicitly to compare against a pre-deploy or pre-incident period. It does not need to be the same length as the current window — rates are normalized per second.

## query.severityLevels / query.serviceNames / query.searchTerm / query.filterGroup

Same as `logs-patterns`; applied to **both** windows. Scoping by service is recommended — it prunes both scans and focuses the sample budget.

# Examples

## What changed during the incident vs. just before it

```json
{
  "query": {
    "dateRange": { "date_from": "2026-07-07T09:30:00Z", "date_to": "2026-07-07T10:30:00Z" },
    "serviceNames": ["checkout"]
  },
  "baselineDateRange": { "date_from": "2026-07-07T08:00:00Z", "date_to": "2026-07-07T09:00:00Z" }
}
```

## What is new or different today vs. the same time last week

```json
{ "query": { "dateRange": { "date_from": "-1d" } } }
```

## Did the deploy change what the service logs?

```json
{
  "query": {
    "dateRange": { "date_from": "2026-07-07T14:00:00Z" },
    "serviceNames": ["api"]
  },
  "baselineDateRange": { "date_from": "2026-07-07T10:00:00Z", "date_to": "2026-07-07T14:00:00Z" }
}
```
