---
name: fixing-message-size-too-large
description: >
  Diagnoses and fixes the `message_size_too_large` ingestion warning — events silently discarded because the final Kafka message exceeded the ~1MB limit after person and group property enrichment.
  Use when a user asks why events are missing or dropped, why an insight undercounts, when the ingestion warnings page or the `posthog:ingestion-warnings-list` tool shows `message_size_too_large`, or when captures return HTTP 413.
  Covers the two distinct failure modes (capture-time rejection vs silent pipeline drop), how accumulated person or group properties make small events undeliverable, per-SDK fixes, and how to verify the fix.
---

# Fixing `message_size_too_large`

The event was **dropped during ingestion** — it never reached PostHog's events table — because the fully-enriched Kafka message exceeded the ~1MB size limit.
Category `size`, severity `error`: this is data loss, not a cosmetic warning.

## The critical insight: the limit applies AFTER enrichment

There are two distinct failure modes, and they look completely different from the app's side:

1. **Rejected at capture** — the event is already too large when sent. The SDK gets an HTTP 413 back, so the failure is visible in SDK logs/error handlers. No ingestion warning is produced for this mode.
2. **Dropped in the pipeline (this warning)** — the event passed capture fine (SDK saw success), but during ingestion PostHog copies the person's properties **and the properties of every group the event belongs to** onto the event. If those have accumulated large values, that enrichment pushes the message past the limit and it is dropped **silently** — the client believes it succeeded.

The total budget is shared: `event properties + person properties + group properties < ~1MB`.
Three consequences:

- A person with ~1MB of person properties makes **all of their events** undeliverable, no matter how small each event is.
- A bloated group (e.g. an organization with a huge settings blob in `$group_set`) makes **every event tagged with that group** undeliverable — potentially across many users at once. Many users affected simultaneously is the signature of a group-side cause.
- An event that is _itself_ large (say 700KB — under the capture limit) can be pushed over by even modest person/group properties. A big event and moderately big person can each look fine in isolation and still fail together.

## Diagnose

1. List the warnings: use the `posthog:ingestion-warnings-list` tool with `type: message_size_too_large` (or the Ingestion warnings page under Data management). Samples carry `event_uuid` and `distinct_id`; `pipeline_step` is `emit-event` (single event) or `flush` (batched person/group writes).
2. Read the repetition pattern in the samples — but resolve distinct IDs to persons before concluding. Distinct IDs are not persons: identified users routinely carry several distinct IDs (anonymous IDs, emails, device IDs) that all map to one merged person, whose properties inflate events sent under **any** of them. Use `posthog:persons-list` (filter by the sampled `distinct_id`) to fetch the person behind it first, then read the pattern at the person level:
   - Same person recurring (even under different distinct IDs) → that person's profile is inflated.
   - Many different _persons_, same event name → the event itself carries a huge payload.
   - Many different persons whose events share a group → group properties are inflated.
3. **Check the event itself first** — it's the cheapest check. Look at how the event is constructed in code, and measure recent surviving occurrences with `posthog:execute-sql`: `SELECT length(properties) FROM events WHERE event = '<name>' ORDER BY timestamp DESC LIMIT 10`. Anything in the hundreds of KB means the event is (most of) the problem.
4. **Check the person**: inspect the size and shape of the resolved person's properties — via the person page, or `posthog:execute-sql`: `SELECT length(properties) FROM persons WHERE id = '<person_id>'`.
5. **Check the groups**: if the affected events carry `$groups`, inspect each group's properties the same way — a single fat group poisons every event that references it.
6. Grep the app code for the event name / `$set` / `groupIdentify` sites feeding those properties: base64 blobs, file contents, entire API responses, or unbounded accumulation (`interaction_1`, `interaction_2`, …) are the usual suspects.

## Fix

The fix is always the same shape: **send references, not payloads**, and keep person and group properties bounded.

- Never attach file contents, images, base64 data, raw documents, or full API responses to event properties, `$set`, or `$group_set`. Store them in your own storage and send an ID or URL.
- Cap accumulating person/group properties: don't mirror an ever-growing CRM or interaction history onto the person or organization. Keep a bounded summary (counts, last-N, flags).
- If a person is already inflated, a one-time `$unset` cleanup of the oversized keys is needed — until then that person's events keep being dropped even after the code fix. `$unset` deletes person data irreversibly and cohorts/flags/filters may depend on those properties, so **propose it to the user and get their approval**; run it as a throwaway one-off, never as shipped application code. Load `fixing-person-properties-size-violation` for the full cleanup procedure.
- If a group is already inflated, the same applies: propose re-running `groupIdentify` with the oversized keys set to small values (group properties are overwritten per key) and let the user decide.

Per SDK, the bug usually looks like:

- **posthog-js**: `posthog.capture('x', { document: bigString })`, `posthog.setPersonProperties({ history: bigObject })`, a large `register()` payload attached to every event, or `posthog.group('org', id, bigSettingsObject)`.
- **posthog-node**: `client.capture({ properties: { $set: wholeCrmRecord } })` in sync jobs; response bodies logged into properties; `client.groupIdentify({ properties: bigObject })`.
- **posthog-python**: `posthog.capture(..., properties={'payload': json.dumps(obj)})` with unbounded `obj`; `$set` in `identify()` or `group_identify()` carrying full profiles.

## Verify

1. Re-run the affected flow.
2. Re-query `posthog:ingestion-warnings-list` with `type: message_size_too_large` and a `since` after your fix — the count for the affected distinct IDs must stop growing. Warnings are debounced per team+type, so judge by "no new occurrences over a real usage window", not by the historical count going down (it won't).
3. Confirm the previously-missing events now appear in the events table.

## Related

- `resolving-ingestion-warnings` — the triage entry point covering every warning type; start there when multiple warning types are present.
- `fixing-person-properties-size-violation` — the same oversized-person-properties root cause, caught at the person store instead of event emit. If you see both warnings for the same distinct IDs, fix the person properties first.
