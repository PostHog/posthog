---
name: resolving-ingestion-warnings
description: >
  Entry point for diagnosing and resolving PostHog ingestion warnings — problems recorded while ingesting events (dropped events, rejected person merges, oversized payloads, invalid data).
  Use when a user asks why events are missing, dropped, or undercounted, why person merges or identify calls don't work, or whether their event ingestion is healthy — and whenever the `ingestion-warnings-list` tool returns results.
  Explains how to read a warning's category and severity, then routes each warning type to its meaning and fix, deferring to dedicated `fixing-<type>` skills where they exist.
---

# Resolving ingestion warnings

Ingestion warnings record problems PostHog hit while ingesting a project's events.
They are the first place to look when events are missing, counts are lower than expected, or identify/merge calls don't behave.

## Workflow

1. **List the warnings**: call `ingestion-warnings-list` (defaults to the last 24h; widen with `since: '-7d'`, narrow with `severity` or `type`). Each entry has a count, a sparkline, and recent samples with the affected `event_uuid` / `distinct_id` / `person_id` / `group_key`.
2. **Triage by severity** — it encodes what happened to the data:
   - `error` — the event or update was **dropped**. Data loss; fix these first.
   - `warning` — ingested, but modified or partially rejected.
   - `info` — informational, or an intentional, team-configured drop.
3. **Route by type** using the table below. Where a dedicated `fixing-<type>` skill exists, load it — it has the full diagnosis and per-SDK fixes.
4. **Verify any fix** the same way: re-run the affected flow, re-query `ingestion-warnings-list` with a `since` after the fix, and confirm the type's count stops growing. Warnings are debounced per team+type+key, so judge by "no new occurrences", not by historical counts shrinking.

One identity caveat that applies throughout: **distinct IDs are not persons**. An identified user usually has several distinct IDs mapping to one person; resolve sampled distinct IDs to persons (persons tools) before reasoning about patterns.

## Warning types and fixes

### Size (`size`)

| Type                                   | What happened                                                                                  | Fix                                                                                                                                               |
| -------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `message_size_too_large`               | Event dropped: >1MB after person/group properties were copied onto it                          | Load the `fixing-message-size-too-large` skill — covers the enrichment mechanism, diagnosis, and per-SDK fixes                                    |
| `person_properties_size_violation`     | A person-properties update was rejected: the person's stored properties would exceed the limit | Load the `fixing-person-properties-size-violation` skill — covers the three growth patterns, the code fix, and the user-approved `$unset` cleanup |
| `person_upsert_message_size_too_large` | A person update was too large to persist                                                       | Same root cause and fix as `person_properties_size_violation`                                                                                     |
| `group_upsert_message_size_too_large`  | A group update was too large to persist                                                        | Trim `$group_set` payloads; groups should carry bounded metadata, not documents                                                                   |
| `group_key_too_long`                   | `$groupidentify` dropped: group key over 400 chars                                             | Load the `fixing-group-key-too-long` skill — a payload/token was passed where the group ID belongs                                                |

### Person merges (`merge`)

| Type                                    | What happened                                                                                            | Fix                                                                                                                                                                               |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cannot_merge_already_identified`       | Merge refused: both persons are already identified. The accounts silently stayed separate                | Load the `fixing-cannot-merge-already-identified` skill — covers the identify/reset flow fixes; joining two identified users is a manual one-off decision, never application code |
| `cannot_merge_with_illegal_distinct_id` | Merge refused: the distinct ID is a placeholder (`undefined`, `null`, `[object Object]`, `anonymous`, …) | Load the `fixing-cannot-merge-with-illegal-distinct-id` skill — a variable is unset at the identify/alias callsite                                                                |
| `merge_race_condition`                  | Concurrent merges collided on the same persons; the operation was dropped                                | Deduplicate parallel `identify`/`alias` calls for the same user (e.g. only identify once per session, not per request)                                                            |

### Event validation (`event`)

| Type                                                                                                                                                         | What happened                                                                                                          | Fix                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `client_ingestion_warning`                                                                                                                                   | The SDK itself reported a problem                                                                                      | Read `details.message` — it states the exact client-side issue                                                                                                             |
| `ignored_invalid_timestamp`                                                                                                                                  | `timestamp` didn't parse; the event was kept with the server time                                                      | Load the `fixing-ignored-invalid-timestamp` skill — send ISO 8601; the event was kept at server time                                                                       |
| `schema_validation_failed`                                                                                                                                   | Event dropped: it violates a schema the team enforces for that event                                                   | Compare `details.errors` against the payload; align the code or update the schema                                                                                          |
| `skipping_event_invalid_distinct_id`                                                                                                                         | Event dropped: distinct ID over 400 chars                                                                              | Load the `fixing-skipping-event-invalid-distinct-id` skill — a token/payload was passed as the distinct ID                                                                 |
| `invalid_ai_token_property`                                                                                                                                  | An `$ai_*` token property wasn't numeric; it was nulled                                                                | Load the `fixing-invalid-ai-token-property` skill — token counts must be plain numbers                                                                                     |
| `invalid_process_person_profile`                                                                                                                             | `$process_person_profile` wasn't boolean; the default (true) was used                                                  | Load the `fixing-invalid-process-person-profile` skill — a stringified boolean silently opts back into person processing                                                   |
| `invalid_event_when_process_person_profile_is_false`                                                                                                         | `$identify`/`$create_alias`/`$merge_dangerously`/`$groupidentify` dropped because the event disabled person processing | Load the `fixing-invalid-event-when-process-person-profile-is-false` skill — identity events require person processing                                                     |
| `event_dropped_too_old`                                                                                                                                      | Intentional: the event is older than the team's configured drop threshold                                              | Expected if the threshold is deliberate; otherwise fix client timestamps or adjust the team setting. Mind mobile SDKs: offline queues legitimately deliver days-old events |
| `cookieless_missing_timestamp` / `cookieless_timestamp_out_of_range` / `cookieless_missing_user_agent` / `cookieless_missing_ip` / `cookieless_missing_host` | Cookieless-mode event dropped: a field required to compute the cookieless ID was missing or invalid                    | Server-side cookieless captures must forward the original request's timestamp, user agent, IP, and host                                                                    |

### Heatmaps (`event`)

| Type                                        | What happened                                                                  | Fix                                                                      |
| ------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `invalid_heatmap_data`                      | `$heatmap_data` didn't parse; the heatmap portion was dropped (event survived) | Almost always hand-built heatmap payloads — let posthog-js generate them |
| `rejecting_heatmap_data_with_invalid_url`   | Heatmap entry keyed by an invalid URL                                          | Keys must be valid URLs                                                  |
| `rejecting_heatmap_data_with_invalid_items` | Heatmap URL mapped to a non-array                                              | Each URL must map to an array of heatmap items                           |

### Error tracking (`event`)

| Type                                         | What happened                                                  | Fix                                                                                            |
| -------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `error_tracking_exception_processing_errors` | A `$exception` event was ingested but symbolication hit errors | Read `details.errors`; usually missing/mismatched source maps — re-upload them for the release |

### Transformations (`transformation`)

| Type                              | What happened                                                        | Fix                                                                                                 |
| --------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `event_dropped_by_transformation` | A transformation the team configured dropped the event (intentional) | If unexpected, review the transformation named in the details — its filter is broader than intended |

### Session replay (`replay`)

| Type                                      | What happened                                         | Fix                                                                                                        |
| ----------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `replay_lib_version_too_old`              | Recording sent by an outdated posthog-js (1.x < 1.75) | Upgrade posthog-js                                                                                         |
| `message_contained_no_valid_rrweb_events` | A replay message carried no usable snapshot data      | Usually a broken custom proxy/transport or very old SDK — verify replay traffic reaches PostHog unmodified |
| `message_timestamp_diff_too_large`        | Replay snapshot timestamps far from arrival time      | Client clock skew or replayed/buffered traffic — check for delayed batch re-sends                          |
