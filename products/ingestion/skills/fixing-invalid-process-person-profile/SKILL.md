---
name: fixing-invalid-process-person-profile
description: >
  Diagnoses and fixes the `invalid_process_person_profile` ingestion warning — an event carried a non-boolean `$process_person_profile` value, so PostHog ignored it and used the default (true).
  Use when a user asks why person profiles are being created despite opting out, why anonymous-event settings aren't taking effect, or when `ingestion-warnings-list` shows `invalid_process_person_profile`.
---

# Fixing `invalid_process_person_profile`

An event set `$process_person_profile` to something other than a boolean (`"false"`, `"yes"`, `0`, …).
Only a real boolean is valid, so PostHog **ignored the property and defaulted to `true`** — the event was ingested and a person profile was processed anyway.
Category `event`, severity `warning`.

## Why it matters

`$process_person_profile: false` is how you mark events as anonymous (cheaper, no person profile). A stringified `"false"` silently opts you back **in** — you get person processing (and its cost) you meant to avoid.

## Diagnose

1. `ingestion-warnings-list` with `type: invalid_process_person_profile`. The sample details show the exact `$process_person_profile` value received — its type reveals the bug (`"false"` = string from config/env, `0` = numeric flag).
2. Grep the app for `$process_person_profile` / `process_person_profile` and check the value's type at the callsite — env vars and JSON configs are the usual source of stringified booleans.

## Fix

Pass a real boolean:

```js
posthog.capture({
  distinctId,
  event: 'page viewed',
  properties: { $process_person_profile: false }, // boolean, not 'false'
})
```

If the value comes from config, parse it (`value === 'true'`) before it reaches the SDK. In posthog-js, prefer the supported config (`person_profiles: 'identified_only'`) over hand-setting the property per event.

## Verify

Re-query `ingestion-warnings-list` with a post-fix `since` — no new occurrences — and confirm new anonymous events stop creating person profiles.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-invalid-event-when-process-person-profile-is-false` — the sibling warning: a valid `false` combined with an event that requires person processing.
