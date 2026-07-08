---
name: fixing-person-properties-size-violation
description: >
  Diagnoses and fixes the `person_properties_size_violation` ingestion warning — a person-properties update ($set/$set_once/identify) was rejected because the person's stored properties would exceed PostHog's size limit.
  Use when a user asks why person properties aren't updating, why a person profile is stale or huge, or when `ingestion-warnings-list` shows `person_properties_size_violation`.
  Covers why the limit exists, why the warning undercounts (sampled enforcement), the knock-on effect on event delivery, the three growth patterns (dynamic keying, big payloads, deep nesting) and how to detect each, plus the two-part fix: a code change and a user-approved one-time `$unset` cleanup.
---

# Fixing `person_properties_size_violation`

A person-properties update was **rejected**: applying it would push the person's stored properties past PostHog's size limit (on the order of 1MB of JSON).
Category `size`, severity `error`: the event itself was ingested, but the `$set`/`$set_once` payload it carried was **not applied** — the person's profile is now silently stale.

## Three things that make this warning treacherous

1. **The rejection is silent** — the capture call succeeded; only the property update was discarded. Code keeps "updating" a profile that never changes.
2. **It undercounts** — the size check runs on a sample of person updates, so one warning implies many more rejected or at-risk updates for the same person.
3. **It has a blast radius beyond properties** — person properties are copied onto every event during ingestion, so a person near the limit also inflates their events toward the event size limit. If you see `message_size_too_large` for the same distinct IDs, it's the same root cause (load `fixing-message-size-too-large`).

## The three ways person state grows

Diagnosing means identifying which growth pattern you're looking at — each has a different signature and a different fix:

| Pattern            | What it looks like                                                                                                                  | Signature                                                                                                             |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Dynamic keying** | Keys generated from data: `interaction_1042`, `viewed_2026-07-08`, `feature_<uuid>_used`                                            | Huge **key count**; each value can be tiny. Size arrives by accumulation — every update adds keys, none ever leave    |
| **Big payloads**   | A few monstrous values: a mirrored CRM record, a base64 blob, a full API response, `$set_once` of a signup snapshot                 | Normal key count; a handful of keys dominate the **value size** ranking                                               |
| **Deep nesting**   | A plausible-looking key (`settings`, `metadata`, `profile`) holding a deeply nested object that grows a level or a branch at a time | Neither count nor top-level ranking looks alarming until you open the value — the size hides **inside** the structure |

These combine: a dynamically-keyed map of nested objects is the worst case and typically comes from "just sync the whole thing" integrations.

## Diagnose

1. List the warnings with `ingestion-warnings-list` (`type: person_properties_size_violation`). Samples carry `person_id` and `distinct_id`. Remember distinct IDs are not persons — resolve them (persons tools); the person's properties are shared across all of their distinct IDs.
2. Profile the person's properties against the three patterns:
   - **Count the keys** — hundreds+ means dynamic keying; look for the generated-name pattern.
   - **Rank values by size** (`JSONExtractKeys(properties)` + `length()` of each value via SQL, or eyeball the person page) — a few dominant keys means big payloads.
   - **Open the large values** — if a "reasonable" key holds a deep object tree, it's the nesting pattern; note which branch grows.
3. Find the writer: grep the app code for the `$set` / `$set_once` / `identify` / `setPersonProperties` callsites producing that pattern — key-name templates for dynamic keying, sync jobs for big payloads, incremental merge-into-object logic for nesting.

## Fix

The fix has two parts: a **code change** so the profile stops growing, and a **one-time cleanup** of the persons that are already inflated. Both are needed — the code change alone doesn't unbreak affected persons (their updates keep failing until the stored blob is back under the limit), and cleanup without the code change just buys time until it reoccurs.

### 1. Code change — match the fix to the pattern

Person properties are for **current state** — bounded facts about the user (plan, role, counts, flags, last-N summaries):

- **Dynamic keying** → never template data into key names. Per-thing facts belong in **events** (query them with aggregations); if you truly need per-key state, keep a bounded map (last N, or counts per category).
- **Big payloads** → store the payload in your own storage and `$set` a reference (ID/URL) plus the few fields you actually filter on.
- **Deep nesting** → flatten: extract the handful of leaf fields analytics needs into top-level properties and stop syncing the container object.

### 2. One-time cleanup — propose `$unset`, don't run it unprompted

`$unset` **deletes person data irreversibly**, and other things may depend on those properties — cohorts, feature flag conditions, insight filters. Treat it as a remediation the **user decides on**:

- Present the affected persons and the exact keys you propose to remove, with their sizes, and check whether any cohort/flag/filter references them before recommending deletion.
- Only after the user agrees, run it — as a throwaway one-off (script or manual calls), never as code that ships in the application:

```js
posthog.capture({
  distinctId: 'the-affected-user',
  event: 'cleanup oversized profile',
  properties: { $unset: ['crm_record', 'interaction_history'] },
})
```

- `$unset` takes top-level key names. For dynamic keying, generate the list from the key enumeration in Diagnose. For deep nesting, you can't unset a nested path — unset the container and re-`$set` it with its slimmed value.
- Expect more affected persons than the warning samples show — the check is sampled.

## Verify

1. After the cleanup, send a small `$set` (e.g. a `profile_cleaned_at` timestamp) and confirm it appears on the person — proof updates apply again.
2. Re-query `ingestion-warnings-list` with a post-fix `since` — no new occurrences. Judge by absence of new warnings over a real usage window; historical counts don't shrink.
3. If `message_size_too_large` was firing for the same persons, confirm it stopped too.

## Related

- `resolving-ingestion-warnings` — the triage entry point covering every warning type.
- `fixing-message-size-too-large` — the event-side symptom of the same inflated-person root cause; fix the person properties first, then confirm events flow.
