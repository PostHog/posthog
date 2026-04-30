# Trend metrics playbook

For "DAU dropped", "revenue spiked", "clicks fell after the release".

## 1. Zoom in

Rerun `posthog:query-trends` at `interval: "hour"` scoped to the suspicious day(s). A
one-hour cliff is an incident or deploy; a full-day shift is a broader cause (campaign,
cohort change, tracking regression).

## 2. Break down

Try several breakdowns. Use `read-data-schema` to find candidate properties. Pipe
results through [`breakdown_attribution.py`](../scripts/breakdown_attribution.py) — it
ranks by absolute delta and flags offsetting moves. If no segment isolates the delta,
the cause is system-wide.

```json
posthog:query-trends
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "dau" }],
  "breakdownFilter": {
    "breakdowns": [{ "property": "plan", "type": "event" }],
    "breakdown_limit": 10
  }
}
```

## 3. Identify affected users

Run `posthog:query-trends-actors` on the anomalous bucket (or breakdown value that
moved). For UI-shaped drops, pull session recordings for the same segment.

## 4. Errors / logs

`posthog:error-tracking-issues-list` and `posthog:query-logs` for the window. Confirm
timing, plausible mechanism, and user overlap before treating as the cause.

## 5. Cohort composition

Run `posthog:query-lifecycle` on the same event. If the drop is concentrated in one
status (new users didn't arrive, dormant users didn't resurrect), the user mix changed
rather than per-user behavior.
