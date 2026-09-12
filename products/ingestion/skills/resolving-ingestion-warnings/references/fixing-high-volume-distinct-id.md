# Fixing high volume distinct ID

Nothing was dropped.
Capture found one `token:distinct_id` key sending events faster than the platform limiter allows, and degraded those events instead of rejecting them.

This is a platform limit, not a team setting, so there is no threshold to raise.
The fix is always to stop one ID from carrying that much traffic.

## What the events lost

Each limited event was ingested, with two changes:

- **Person processing was turned off.**
  The event does not update person properties, and identify and merge operations do not apply to it.
  Person-property breakdowns and cohorts will look stale for that ID, while event counts stay correct.
- **It was rerouted to overflow.**
  That spreads the hot key across partitions, and in exchange it gives up the ordering guarantee, so events for that ID can be processed out of order.

Both effects are per event, not per ID: the same distinct ID's earlier, unlimited events keep their person processing.

## Why one ID gets that hot

| Pattern                   | What it looks like                                                                               | Is it a bug?                                                        |
| ------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| A constant server-side ID | A backend sends every event under one value — a service name, an account ID, an environment name | Yes. The events cannot be attributed to users                       |
| A placeholder fallback    | `"anonymous"`, `"unknown"`, `"guest"` used when the real ID is unavailable                       | Yes. Every affected user collapses into one person                  |
| A tenant or org ID        | A B2B app captures against the account rather than the user                                      | Usually. Use groups for account-level analysis, not the distinct ID |
| A genuine hot client      | A load test, a crawler, a sync job, or one very active integration                               | Not always. Decide whether the traffic is wanted at all             |

The limiter keys on the token plus the first 200 characters of the distinct ID, so two IDs that share a long common prefix count as one key.

## Diagnose

```sql
SELECT
    JSONExtractString(details, 'distinctId') AS distinct_id,
    JSONExtractInt(details, 'distinctIdCount') AS hot_ids_in_batch,
    JSONExtractString(details, 'lib') AS lib,
    JSONExtractString(details, 'libVersion') AS lib_version,
    sum(JSONExtractInt(details, 'count')) AS limited_events
FROM system.ingestion_warnings
WHERE type = 'high_volume_distinct_id'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY distinct_id, hot_ids_in_batch, lib, lib_version
ORDER BY limited_events DESC
```

Reading the result:

- `distinctId` is present only when the batch had exactly one hot key.
  With several it is omitted, because it would be an arbitrary pick — `distinctIdCount` says how many there were.
- `count` counts limited **events**, not IDs.
- A `lib` naming a server SDK means the sender controls the ID explicitly, so the callsite is the place to look.
  `web` is unusual here, and suggests either a shared ID written by your own code or one very busy browser session.

If the distinct ID is a real one, resolve it with `posthog:persons-list` and look at the person before changing anything — distinct IDs are not persons, and an identified user has several.

## Distinguishing it from a missing-ID problem

Both fire on the same request paths and both point at the distinct ID argument, so they are easy to confuse.
They are opposite failures:

|                            | `high_volume_distinct_id`        | `missing_distinct_id` |
| -------------------------- | -------------------------------- | --------------------- |
| Category / severity        | `quota` / `warning`              | `event` / `error`     |
| `details.pipelineStep`     | `capture_rate_limit`             | `capture_validation`  |
| What happened to the event | Ingested, person processing off  | Dropped               |
| Usual cause                | One ID used for too much traffic | No ID supplied at all |

A placeholder fallback causes both over time: the callsite that returns no ID produces `missing_distinct_id`, and "fixing" it with a constant string moves the problem here.

## Fix

- **Send the real user's ID.**
  On server SDKs, pass the distinct ID per capture call rather than once at client construction, and make it a required argument in your internal wrapper so a constant cannot be the default.
- **Batch without collapsing identities.**
  Batching is a transport concern; each event in a batch still carries its own distinct ID.
  A batch helper that takes one ID for the whole batch is the bug.
- **Use groups for account-level data.**
  Capture against the user and attach the account with `$groupidentify`, so account analysis does not need a shared ID.
- **For genuinely user-less events, turn person processing off deliberately** by setting `$process_person_profile` to `false`.
  The events still need a distinct ID, but you stop paying for person processing you never wanted.
- **For unwanted traffic, stop it at the source.**
  A crawler or a load test pointed at production is not a PostHog configuration problem.

## Verify

Re-query with a timestamp after your change:

```sql
SELECT timestamp, details
FROM system.ingestion_warnings
WHERE type = 'high_volume_distinct_id'
  AND timestamp > '<your fix time>'
ORDER BY timestamp DESC
LIMIT 20
```

Judge by "no new occurrences".
Then confirm the traffic reappears spread over many distinct IDs, and that person properties for the affected users update again.

## Related

- [fixing-capture-validation-rejections.md](fixing-capture-validation-rejections.md) — the rejection family this is most often confused with.
- [fixing-invalid-distinct-ids.md](fixing-invalid-distinct-ids.md) — placeholder IDs, the usual route to a hot key.
- [fixing-merge-race-condition.md](fixing-merge-race-condition.md) — a shared ID that does get person processing builds a "mega person" instead.
