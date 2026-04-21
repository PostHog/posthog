# Query patterns for metric investigation

Copy-pasteable MCP tool call payloads, organized by metric type.
Adapt the `event`, `dateRange`, and property names to the user's metric, but keep the structure.

All payloads assume the anomaly window has been pinned to a known `date_from` (e.g., `"-30d"`,
or ISO dates). For tighter windows, use explicit ISO dates:
`{"date_from": "2026-03-01", "date_to": "2026-03-14"}`.

## When to use `posthog:execute-sql` instead

The structured query tools (`posthog:query-trends`, `posthog:query-funnel`,
`posthog:query-retention`, `posthog:query-paths`, `posthog:query-stickiness`,
`posthog:query-lifecycle`, `posthog:query-trends-actors`) use LLM-curated schemas
(simpler than raw `TrendsQuery` / `FunnelsQuery` / etc. — they strip rendering-only fields)
and their output composes cleanly with `posthog:query-trends-actors` for the actor drilldown.
Prefer them for anything that fits.

Reach for `posthog:execute-sql` (HogQL) only when the question cannot be expressed by a
structured tool. Typical cases:

- **Ratios across events** — "how did event A per user per day compare to event B per user per day?"
- **Joins with data-warehouse tables** — "events where the person is in a data-warehouse cohort"
- **Custom aggregation** — "p90 of `properties.duration` per day, filtered to logged-in users"

If the question fits a structured tool, use the structured tool. Do not default to HogQL.

## Trend metrics

### Zoom in with a finer interval

When a daily point looks anomalous, rerun the same trend scoped tightly to the suspicious
day(s) with `interval: "hour"`. The shape often answers the hypothesis: a one-hour spike is
an incident, a full-day dip is a broader cause.

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "2026-03-10T00:00:00Z", "date_to": "2026-03-10T23:59:59Z" },
  "interval": "hour",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }]
}
```

Use `interval: "minute"` for even tighter windows (e.g., a 2-hour incident window).

### Break down a trend to isolate the affected segment

Run several breakdowns — you rarely know in advance which dimension reveals the affected
segment. Typical dimensions to try:

- **Standard event context** — `$browser`, `$browser_version`, `$os`, `$device_type`,
  `$screen_width`, `$geoip_country_code`. Always available.
- **Feature-flag exposure** — `$feature/<flag_key>` on the event (post-release).
- **User state** — `is_identified`, `$is_first_session`, plan / tier on person.
- **Custom event properties** attached to the specific event (discovered via
  `posthog:properties-list` with `type: "event"` and `eventName: "<event>"`) —
  e.g. `plan`, `tier`, `feature_area`, `channel`.
- **Technical / version** — `app_version`, `$lib_version`.

Call `posthog:query-trends` with the metric plus a `breakdownFilter`:

```json
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

Rerun with different breakdowns until one value explains most of the delta.
If two dimensions each explain part of the move, use a compound breakdown (up to three
properties in the `breakdowns` array).

### Get the actors behind an anomalous point

```json
{
  "kind": "InsightActorsQuery",
  "source": {
    "kind": "TrendsQuery",
    "dateRange": { "date_from": "2026-03-10", "date_to": "2026-03-10" },
    "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "dau" }],
    "breakdownFilter": { "breakdowns": [{ "property": "plan", "type": "event" }] }
  },
  "day": "2026-03-10",
  "breakdown": "free"
}
```

### Check if the drop is cohort-composition

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }]
}
```

### Session recordings for the affected segment

Pull recordings matching the affected window / segment via
`posthog:query-session-recordings-list`:

```json
{
  "kind": "RecordingsQuery",
  "dateRange": { "date_from": "2026-03-10", "date_to": "2026-03-10" },
  "properties": [{ "type": "event", "key": "plan", "operator": "exact", "value": "free" }],
  "limit": 20
}
```

Then retrieve individual recordings via `posthog:session-recording-get` with the session ID.

### Cross-check against errors

```json
{
  "kind": "ErrorTrackingQuery",
  "dateRange": { "date_from": "-7d" }
}
```

Or call `posthog:error-tracking-issues-list` for the current open issues. Correlate with
the anomaly window.

## Funnel metrics

### Confirm which step regressed

```json
{
  "kind": "FunnelsQuery",
  "dateRange": { "date_from": "-30d" },
  "series": [
    { "kind": "EventsNode", "event": "signed up" },
    { "kind": "EventsNode", "event": "completed onboarding" },
    { "kind": "EventsNode", "event": "first purchase" }
  ],
  "funnelsFilter": { "funnelWindowInterval": 7, "funnelWindowIntervalUnit": "day" }
}
```

Compare to a baseline window using `compareFilter: {"compare": true}`.

### Decompose entries vs. completions at the failing step

Run two `posthog:query-trends` calls — one for entries to step N, one for completions of step N:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "<event at step N>", "math": "dau" }]
}
```

### Get the users who dropped out at step N

`posthog:query-trends-actors` accepts only a trends source today. Work around it by running a
trends query for users who completed step N-1 but did **not** complete step N within the funnel
window, then drill into the actors of that trend:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    {
      "kind": "EventsNode",
      "event": "<event at step N-1>",
      "math": "dau",
      "properties": [
        {
          "type": "hogql",
          "key": "not exists (select 1 from events e2 where e2.person_id = events.person_id and e2.event = '<event at step N>' and e2.timestamp between events.timestamp and events.timestamp + interval 7 day)"
        }
      ]
    }
  ]
}
```

Adjust the `interval 7 day` to match the funnel window. Then call `posthog:query-trends-actors`
on this trend to get the dropped-out users.

For a simpler approximation that doesn't require HogQL, run a trend on step-N-1 completions and
another on step-N completions, and manually diff the actor lists.

### Discover what they do instead

```json
{
  "kind": "PathsQuery",
  "dateRange": { "date_from": "-30d" },
  "pathsFilter": {
    "endPoint": "<event at step N>",
    "includeEventTypes": ["$pageview", "custom_event"],
    "edgeLimit": 50
  }
}
```

### Session recordings for dropouts

```json
{
  "kind": "RecordingsQuery",
  "dateRange": { "date_from": "-30d" },
  "actions": [{ "id": "<action id for the failing step>" }],
  "limit": 20
}
```

## Retention metrics

### Isolate the affected cohort

`targetEntity` / `returningEntity` use `{type: "events", name: "<event>"}` (or
`{type: "actions", id: <id>, name: "..."}`). They are nested inside `retentionFilter`.

```json
{
  "kind": "RetentionQuery",
  "dateRange": { "date_from": "-90d" },
  "retentionFilter": {
    "targetEntity": { "type": "events", "name": "$pageview" },
    "returningEntity": { "type": "events", "name": "$pageview" },
    "totalIntervals": 8,
    "period": "Week",
    "retentionType": "retention_first_time"
  }
}
```

### Scope to the retained-activity event

Use `posthog:cohorts-create` (or reuse an existing cohort via `posthog:cohorts-list`) for the
affected start period, then filter a trend query on it:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "series": [{ "kind": "EventsNode", "event": "core_action", "math": "dau" }],
  "properties": [{ "type": "cohort", "key": "id", "value": 42, "operator": "in" }]
}
```

### Split the dropout with lifecycle

Run `posthog:query-lifecycle` scoped to the affected cohort to separate new users who never
returned from returning users who churned later.

## Stickiness metrics

### Compare segments (no breakdownFilter support)

`AssistantStickinessQuery` does not support `breakdownFilter`. To compare segments, run one
query per segment with property filters on the series:

```json
{
  "kind": "StickinessQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "properties": [{ "type": "person", "key": "plan", "value": "pro", "operator": "exact" }]
    }
  ]
}
```

Rerun with `"value": "free"` (or other segment values) and compare results side by side. To
drill into actors for the low-stickiness segment, run a `posthog:query-trends` on a key
engagement event filtered to that segment, then `posthog:query-trends-actors` on that trend.

### Compare engagement events between sticky and non-sticky cohorts

Once you've identified a sticky cohort (high stickiness) and a non-sticky cohort (low
stickiness) — either via existing cohorts or ad-hoc filters — run trends on candidate core
events scoped to each:

```json
{
  "kind": "TrendsQuery",
  "dateRange": {"date_from": "-30d"},
  "interval": "day",
  "series": [
    {"kind": "EventsNode", "event": "candidate_core_event", "math": "dau"}
  ],
  "properties": [
    {"type": "cohort", "key": "id", "value": <sticky_cohort_id>, "operator": "in"}
  ]
}
```

Rerun with the non-sticky cohort's filter. Events where the two series diverge sharply are the
ones that drive stickiness.

## Lifecycle metrics

### Start with lifecycle itself

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }]
}
```

### Segment the affected status (no breakdownFilter support)

`AssistantLifecycleQuery` does not support `breakdownFilter`. Run one query per segment with
property filters on the series:

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "properties": [{ "type": "event", "key": "$geoip_country_code", "value": "US", "operator": "exact" }]
    }
  ]
}
```

Rerun per segment value. To focus on a specific lifecycle status rather than all four, set
`lifecycleFilter.toggledLifecycles` to an array like `["new"]` or `["returning"]`.

### Onboarding dropout (for new-user drops)

Identify the canonical first-session event for the project first — call
`posthog:event-definitions-list` and look for `$session_start`, `$pageview`, or a
product-specific signup event. Then:

```json
{
  "kind": "PathsQuery",
  "dateRange": { "date_from": "-30d" },
  "pathsFilter": {
    "startPoint": "<first-session event name from event-definitions-list>",
    "includeEventTypes": ["$pageview", "custom_event"],
    "edgeLimit": 50
  }
}
```

## Annotations

Call `posthog:annotations-list` with no parameters, then filter the returned list
client-side to annotations whose `date_marker` falls within or just before the anomaly window.
There is no date parameter on this tool today.

```json
{}
```

Look for keywords like "deploy", "release", "campaign", "incident" in the `content` field.

## Discovering the right breakdown properties

Always discover before breaking down. A breakdown on a non-existent property produces an
empty chart that looks like "no data" but really means "wrong property name".

### Custom properties attached to a specific event

The most valuable breakdowns for product-specific metrics are usually the custom properties
the app sets when capturing the event (e.g. `plan`, `tier`, `feature_area`, `channel`).
Scope `posthog:properties-list` to the event to surface them:

```json
{
  "type": "event",
  "eventName": "<your event>"
}
```

By default this excludes core PostHog properties (`$browser`, `$current_url`, etc.) so
app-specific ones surface naturally. Set `"includePredefinedProperties": true` if you also
want the built-ins in the same list.

### Person-level properties

```json
{
  "type": "person"
}
```

### Finding the event itself

If the user's "metric" references an event whose exact name you don't know, call
`posthog:event-definitions-list` with no filters to enumerate events, then search the returned
list for the one the user meant.
