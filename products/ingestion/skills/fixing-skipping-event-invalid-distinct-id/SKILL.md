---
name: fixing-skipping-event-invalid-distinct-id
description: >
  Diagnoses and fixes the `skipping_event_invalid_distinct_id` ingestion warning — an event was dropped because its distinct ID exceeded 400 characters.
  Use when a user asks why some events are missing, or when `ingestion-warnings-list` shows `skipping_event_invalid_distinct_id`.
---

# Fixing `skipping_event_invalid_distinct_id`

An event was **dropped** because its distinct ID was longer than 400 characters.
Category `event`, severity `error`: the event never reached PostHog's events table.

## What it means in your code

A distinct ID identifies a user — it should be a short stable value (user ID, UUID, email). 400+ characters means something else was passed as the ID:

- a JWT or session token,
- a serialized object / JSON,
- a URL, or a concatenation bug gluing several fields together.

Every event sent with that value is silently lost until fixed, so treat this as data loss for the affected code path.

## Diagnose

1. `ingestion-warnings-list` with `type: skipping_event_invalid_distinct_id`. The sample details include the truncated `distinctId` and its length — the shape of the value identifies the bug (dots and base64 → a JWT; braces → serialized JSON).
2. Grep the app for where that value could reach the SDK's distinct ID: `identify(`, `capture(` with an explicit `distinctId`, or custom wrapper helpers.

## Fix

Pass the user's stable identifier, nothing else:

```js
client.capture({ distinctId: user.id, event: 'plan upgraded' })
```

Add a guard/type so tokens and objects can't flow into the ID argument — this is the same class of bug as `cannot_merge_with_illegal_distinct_id`, just with an oversized value instead of a placeholder.

## Verify

Re-run the affected flow, re-query `ingestion-warnings-list` with a post-fix `since` — no new occurrences — and confirm the events now arrive under the correct person.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-cannot-merge-with-illegal-distinct-id` — the placeholder-ID variant of the same callsite bug.
