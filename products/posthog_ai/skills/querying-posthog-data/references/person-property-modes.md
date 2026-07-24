# Person property modes

PostHog has two modes for how `person.properties.*` behaves when querying the `events` table.
The active mode is included in the project metadata.

## Person-on-events mode (event-time)

When person-on-events is enabled, person properties are stored on each event at ingestion time.
`person.properties.X` on the `events` table returns the value as it was when the event was captured.

- The same person can have different property values across different events
- `argMin(person.properties.X, timestamp)` returns the earliest value — useful for cohort assignment
- `argMax(person.properties.X, timestamp)` returns the latest value for that time range
- Grouping by `person.properties.X` can place the same person in multiple groups if the value changed

```sql
-- Correct: get the user's membership type at their first event each day
SELECT
    distinct_id,
    dateTrunc('day', timestamp) AS day,
    argMin(person.properties.currentMembershipType, timestamp) AS membership_at_start_of_day
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY distinct_id, day
```

## Query-time mode (current value)

When person-on-events is disabled, person properties are joined at query time.
`person.properties.X` on the `events` table always returns the person's current (latest) value.

- The value is the same across all events for a given person, regardless of when the event occurred
- `argMin(person.properties.X, timestamp)` and `argMax(person.properties.X, timestamp)` return the same value — they are no-ops for segmentation
- To get historical values, you need event properties that captured the value at the time (e.g., `properties.membershipType` set via `$set` on the event itself)

```sql
-- In query-time mode, this returns the CURRENT membership type for all events
-- It does NOT reflect what the type was when the event occurred
SELECT
    person.properties.currentMembershipType AS current_type,
    count() AS event_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY current_type
```

## The `persons` table

Regardless of mode, querying `persons.properties.X` directly (from the `persons` table, not via `events`) always returns the current value.

## How to check the mode

The project metadata in the system prompt indicates which mode is active.
If you are unsure, ask the user whether their person properties change over time and whether they need historical values.
