# Funnel metrics playbook

For "conversion fell", "drop-off increased at step X".

## 0. Rule out an incomplete latest bucket

If `(now − latest_bucket_start) < funnel_window`, users in the bucket haven't had time
to convert. Tells:

- Drop is uniform across breakdowns (real regressions usually aren't).
- First-step volume is stable or growing.
- Prior bucket sits on the historical baseline.

If incomplete: report it as the cause; suggest setting `dateRange.date_to` one funnel
window in the past, and offer to annotate.

## 1. Which step regressed

`FunnelsQuery` doesn't support `compareFilter` — run the funnel twice with date ranges
of equal length and compare.

```json
posthog:query-funnel
{
  "kind": "FunnelsQuery",
  "dateRange": { "date_from": "-7d" },
  "series": [
    { "kind": "EventsNode", "event": "signed up" },
    { "kind": "EventsNode", "event": "completed onboarding" },
    { "kind": "EventsNode", "event": "first purchase" }
  ],
  "funnelsFilter": { "funnelWindowInterval": 7, "funnelWindowIntervalUnit": "day" }
}
```

Then rerun with `"dateRange": { "date_from": "-14d", "date_to": "-7d" }`.

## 2. Entries or completions?

Run `posthog:query-trends` on the events at step N-1 and step N. Steady entries with
falling completions = problem at that step. Falling entries = problem upstream.

## 3. Who dropped off

`posthog:query-trends-actors` only accepts a trends source. Run trends on step N-1
completions and step N completions for the same window, drill into actors of each, and
diff — users present in the first but not the second are the drop-offs.

## 4. Errors / logs

Filter `posthog:error-tracking-issues-list` and `posthog:query-logs` to the surface
where step N lives — a 500 on the submit endpoint can plausibly cause failures; a
console warning elsewhere usually can't.

## 5. What they do instead

`posthog:query-paths` with `endPoint` set to the failing step. Paths that don't reach
that endpoint show where users bail.
