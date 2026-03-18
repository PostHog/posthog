# HogQL syntax extensions

These functions are unique to HogQL and not available in standard ClickHouse.

## Visualization

### `sparkline(array)`

Creates a tiny inline graph from an array of integers. Useful for visualizing trends in table cells.

```sql
-- Basic sparkline
SELECT sparkline(range(1, 10)) FROM (SELECT 1)

-- 24-hour pageview sparkline per URL
SELECT
    pageview,
    sparkline(arrayMap(h -> countEqual(groupArray(hour), h), range(0,23))),
    count() as pageview_count
FROM (
    SELECT
        properties.$current_url as pageview,
        toHour(timestamp) AS hour
    FROM events
    WHERE timestamp > now() - interval 1 day AND event = '$pageview'
) subquery
GROUP BY pageview
ORDER BY pageview_count desc
```

## Version handling

### `sortableSemVer(version_string)`

Converts a SemVer version number into a sortable format for ordering purposes.

```sql
SELECT DISTINCT properties.$lib_version
FROM events
WHERE event = '$pageview' AND timestamp >= now() - INTERVAL 1 DAY
ORDER BY sortableSemVer(properties.$lib_version) DESC
LIMIT 10
```

## Session replays

### `recordingButton(session_id)`

Creates a clickable button to view the session replay for a given session ID.

```sql
SELECT
    person.properties.email,
    min_first_timestamp AS start,
    recordingButton(session_id)
FROM raw_session_replay_events
WHERE min_first_timestamp >= now() - INTERVAL 1 DAY
    AND min_first_timestamp <= now()
ORDER BY min_first_timestamp DESC
LIMIT 10
```

## Actions

### `matchesAction(action_name)`

Filters events that match a named action. Actions are named event combinations defined in PostHog.

```sql
SELECT count()
FROM events
WHERE matchesAction('clicked homepage button')
```

## Localization

### `languageCodeToName(code)`

Translates a language code (e.g., 'en', 'fr') to its full language name.

```sql
SELECT
    languageCodeToName('en') AS english,  -- English
    languageCodeToName('fr') AS french,   -- French
    languageCodeToName('pt') AS portuguese, -- Portuguese
    languageCodeToName('ru') AS russian,  -- Russian
    languageCodeToName('zh') AS chinese   -- Chinese
```

## HTML rendering

HogQL supports limited HTML tags for rich output in table visualizations. For security, no attributes are supported except for `<a>` tags.

### Supported tags

- Structure: `<div>`, `<p>`, `<span>`, `<pre>`, `<code>`
- Text formatting: `<em>`, `<strong>`, `<b>`, `<i>`, `<u>`
- Headings: `<h1>`, `<h2>`, `<h3>`, `<h4>`, `<h5>`, `<h6>`
- Lists: `<ul>`, `<ol>`, `<li>`
- Tables: `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>`
- Other: `<blockquote>`, `<hr>`

### Links with `<a>`

Create clickable links. URLs in Table visualization are automatically clickable, but use `<a>` for custom link text.

```sql
SELECT
    properties.$pathname,
    <a href={f'https://posthog.com/{properties.$pathname}'} target='_blank'>Link</a> as link
FROM events
WHERE event = '$pageview'
```

## Text effects

Special tags for visual effects in table output.

### `<blink>`

Makes text blink.

```sql
SELECT <span>is this <blink>{event}</blink> real?</span> FROM events
```

### `<marquee>`

Makes text scroll horizontally.

```sql
SELECT <marquee>scrolling text!</marquee> FROM events
```

### `<redacted>`

Hides text until hovered over.

```sql
SELECT <redacted>hidden until hover</redacted> FROM events
```

### Combined example

```sql
SELECT
    <span>is this <blink>{event}</blink> real?</span>,
    <marquee>so real, yes!</marquee>,
    <redacted>but this one is hidden</redacted>
FROM events
```

## Funnel functions

The three variants differ only in how the breakdown property column is typed.

### `aggregate_funnel` / `aggregate_funnel_array` / `aggregate_funnel_cohort`

7 arguments:

1. `num_steps` (Int) — total number of funnel steps
2. `conversion_window_limit` (Int) — max seconds between first and last step
3. `breakdown_attribution_type` (String) — one of `first_touch`, `last_touch`, `all_events`, or `step_N`
4. `funnel_order_type` (String) — `ordered`, `unordered`, or `strict`
5. `prop_vals` (Array) — breakdown property values to aggregate over
6. `optional_steps` (Array(Int)) — 1-indexed step numbers marked as optional
7. `events_array` (Array(Tuple)) — pre-sorted array of `(timestamp, uuid, breakdown_prop, steps)` tuples per person

Returns an array of tuples: `(step_reached, breakdown_value, timings, event_uuids, steps_bitmask)`.

### `aggregate_funnel_trends` / `aggregate_funnel_array_trends` / `aggregate_funnel_cohort_trends`

8 arguments:

1. `from_step` (Int) — 1-indexed start step for conversion measurement
2. `to_step` (Int) — 1-indexed goal step for conversion measurement
3. `num_steps` (Int) — total number of funnel steps
4. `conversion_window_limit` (Int) — max seconds between first and last step
5. `breakdown_attribution_type` (String) — one of `first_touch`, `last_touch`, `all_events`, or `step_N`
6. `funnel_order_type` (String) — `ordered`, `unordered`, or `strict`
7. `prop_vals` (Array) — breakdown property values to aggregate over
8. `events_array` (Array(Tuple)) — pre-sorted array of `(timestamp, interval_start, uuid, breakdown_prop, steps)` tuples per person

Returns an array of tuples: `(interval_start, success_bool, breakdown_value, event_uuid)`.
