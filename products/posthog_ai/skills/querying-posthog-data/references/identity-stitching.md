# Stitching anonymous and identified events

A user has more than one `distinct_id`.
Before the SDK calls `identify`, events carry an anonymous id that PostHog generates.
After the call, events carry the id you passed to `identify`.

PostHog merges those ids for you at ingestion.
The `events.person_id` column returns the same value for every event of one user, on both sides of the merge.
So `person_id` is the column to group by, count with, and join on.

## Do this

```sql
-- Every event of one user, anonymous and identified alike
SELECT person_id, count() AS event_count, min(timestamp) AS first_seen
FROM events
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY person_id
```

```sql
-- Unique users, not unique devices
SELECT count(DISTINCT person_id) AS users
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 7 DAY
```

```sql
-- A conversion that starts anonymous and ends signed in
SELECT
    person_id,
    min(timestamp) AS first_seen,
    minIf(timestamp, event = 'subscription_started') AS subscribed
FROM events
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY person_id
HAVING countIf(event = 'subscription_started') > 0
```

## Do not do this

Do not build the merge yourself from `$identify` events.
A query that joins `$identify` to map an anonymous id onto a user id repeats work PostHog already did.
It also misses merges that came from other sources, such as `$create_alias` or a server-side call.

Do not use `distinct_id` where you mean a user.
Counting `DISTINCT distinct_id` counts devices and pre-identify sessions as separate users, so it reports more users than you have.

## Related columns

- `person.properties.*` reaches the person behind the event.
  See [person property modes](./person-property-modes.md) for whether those values are historical or current.
- `persons.id` matches `events.person_id`, so you can join the `persons` table on it.
- The `person_distinct_ids` table maps each `distinct_id` to its `person_id`.
  Query it when you want the ids themselves, for example to debug a merge.
