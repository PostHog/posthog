# Fixing the capture validation rejections

Capture rejects these payloads at the edge, before the ingestion pipeline sees them.
The events never land, so they appear in no insight, no session, and no other warning.
The warning row is the only record that the data existed.

All of them share `source = 'capture'` and `details.pipelineStep = 'capture_validation'`.

## Which endpoint rejected the batch

`details.path` names the request path, and the path decides how much was lost.

| `details.path`                                      | Pipeline | What the rejection cost                                                                                                                      |
| --------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `/i/v1/analytics/events`, `/i/v1/ai/events`         | v1       | Only the invalid event was dropped. The rest of the batch was ingested                                                                       |
| `/e/`, `/i/v0/e`, `/batch/`, `/capture/`, `/track/` | legacy   | The **whole request** was rejected on the first invalid event, and `details.count` charges every event in it — one bad event loses the batch |

So `details.count` is a true per-event tally on v1, but on legacy it is the batch size — a caller sending 100-event batches records 100 occurrences per bad request.

Two structural rejections are always whole-request, on both pipelines, because there are no valid events to keep: `empty_batch` and `invalid_batch`.

## What each type means

| Type                         | The payload capture refused                                                                                                | Where to look                                                              |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `missing_distinct_id`        | No usable `distinct_id`: absent, `null`, empty, or whitespace only                                                         | The capture callsite — see below                                           |
| `distinct_id_too_large`      | `distinct_id` over 200 characters                                                                                          | [fixing-invalid-distinct-ids.md](fixing-invalid-distinct-ids.md)           |
| `missing_event_name`         | No event name, or an empty one                                                                                             | A capture call built from a variable that was unset                        |
| `event_name_too_long`        | Event name over 200 characters                                                                                             | An event name built by string concatenation; move the detail to a property |
| `invalid_event_timestamp`    | `timestamp` is not RFC 3339. The event was **dropped**, unlike `ignored_invalid_timestamp`                                 | [fixing-ignored-invalid-timestamp.md](fixing-ignored-invalid-timestamp.md) |
| `malformed_event_properties` | `properties` is not a JSON object — usually a JSON-encoded string, or an array                                             | A serializer that stringifies the property bag before sending              |
| `invalid_options`            | An `options` field could not be read as a boolean (`cookieless_mode`, `disable_skew_correction`, `process_person_profile`) | Whatever sets those options; only the one event was dropped                |
| `missing_event_uuid`         | No `uuid` on the event. v1 requires one; the SDK normally generates it                                                     | A hand-rolled client, or a proxy that strips fields                        |
| `invalid_event_uuid`         | `uuid` is not a UUID                                                                                                       | Same — the value is often an integer ID or a session token                 |
| `duplicate_event_uuid`       | Two events in one batch carry the same `uuid`                                                                              | A retry or buffer-flush bug that resends without regenerating the UUID     |
| `empty_batch`                | The request carried no events                                                                                              | A client flushing on a timer with nothing buffered                         |
| `invalid_batch`              | The batch structure itself could not be read                                                                               | A proxy or gateway rewriting the body                                      |

## Diagnose

1. Pull the rejections and group them, since the attribution details do most of the work:

   ```sql
   SELECT
       JSONExtractString(details, 'lib') AS lib,
       JSONExtractString(details, 'libVersion') AS lib_version,
       JSONExtractString(details, 'path') AS path,
       count() AS warnings,
       sum(JSONExtractInt(details, 'count')) AS events
   FROM system.ingestion_warnings
   WHERE type = 'missing_distinct_id'
     AND timestamp > now() - INTERVAL 7 DAY
   GROUP BY lib, lib_version, path
   ORDER BY events DESC
   ```

   One `lib` with a spread of versions is a callsite bug that has shipped for a while.
   One `lib` at one version is a regression a release introduced — compare the first `timestamp` for that version against your release dates.

2. On v1 only, a rejection that matched exactly one event in its batch also carries `distinctId` and `eventUuid`.
   With several matches both are omitted, because either would be an arbitrary pick.

3. Map `lib` to the callsite.
   `web` is posthog-js; a server SDK names itself (`posthog-python`, `posthog-node`, …).
   Grep that code for the capture call and trace the argument the type table points at.

## Fixing `missing_distinct_id`

The ID is trimmed before it is checked, so an absent field, `null`, `""`, and `"   "` all reject the same way.
The legacy path also accepts `properties.distinct_id` as a fallback; v1 reads only the top-level field, so a client that relied on the fallback starts rejecting when its traffic moves to `/i/v1/analytics/events`.

The fix depends on who is sending.

- **Browser (`web`).**
  posthog-js manages the distinct ID itself, so a missing one means something overrode it: an explicit ID built from unloaded state, a `posthog.reset()` racing a capture, or capture calls issued before `posthog.init()` finished.
  Do not pass an explicit ID for anonymous visitors — let the SDK supply its own, and call `identify` only once the user is known.
- **Server SDKs.**
  Every capture call needs an explicit ID, so the failure is a request that reached your handler without one.
  Resolve the user before capturing, and skip the capture when you cannot:

  ```python
  if user_id:
      posthog.capture("order_placed", distinct_id=user_id)
  ```

  Never substitute a placeholder such as `"anonymous"` or `"unknown"`.
  It passes validation and then collapses every affected user into one person, which is harder to unpick than a dropped event.
  If the event genuinely belongs to no user, send it with person processing off rather than inventing an ID.

- **A proxy or gateway in front of capture.**
  If `lib` is spread across SDKs and versions rather than concentrated, suspect the hop instead of the clients: something is rewriting or stripping the body.
  Compare a request captured at the client against what reaches capture.

## Verify

Re-run the affected flow and re-query, filtered to the type and a timestamp after your fix:

```sql
SELECT timestamp, details
FROM system.ingestion_warnings
WHERE type = 'missing_distinct_id'
  AND timestamp > '<your fix time>'
ORDER BY timestamp DESC
LIMIT 20
```

Judge by "no new occurrences" — the historical rows stay.
Then confirm the events now arrive, under the persons you expect.

## Related

- [fixing-invalid-distinct-ids.md](fixing-invalid-distinct-ids.md) — the pipeline-side distinct ID warnings.
  A broken ID callsite often fires both: capture rejects the empty and oversized values, and the pipeline rejects the placeholder ones.
- [fixing-high-volume-distinct-id.md](fixing-high-volume-distinct-id.md) — the opposite failure.
  A placeholder ID used as a fallback passes validation here and becomes a hot key there.
