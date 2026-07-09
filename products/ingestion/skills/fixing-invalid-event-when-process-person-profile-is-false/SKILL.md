---
name: fixing-invalid-event-when-process-person-profile-is-false
description: >
  Diagnoses and fixes the `invalid_event_when_process_person_profile_is_false` ingestion warning — an `$identify`, `$create_alias`, `$merge_dangerously`, or `$groupidentify` event was dropped because it disabled person processing with `$process_person_profile: false`.
  Use when a user asks why identify or group calls have no effect, or when `posthog:ingestion-warnings-list` shows `invalid_event_when_process_person_profile_is_false`.
---

# Fixing `invalid_event_when_process_person_profile_is_false`

An `$identify`, `$create_alias`, `$merge_dangerously`, or `$groupidentify` event carried `$process_person_profile: false` — but these operations **exist to modify person/group state**, which is exactly what that flag disables. The event was **dropped**.
Category `event`, severity `error`: the identify/alias/group operation never happened.

## What it means in your code

The contradiction usually comes from a global default colliding with specific calls:

- posthog-js configured with `person_profiles: 'never'` (or a wrapper stamping `$process_person_profile: false` on every event) while the app still calls `identify()`/`group()`.
- A cost-saving pass that marked all events anonymous, catching the identity events too.

## Diagnose

1. `posthog:ingestion-warnings-list` with `type: invalid_event_when_process_person_profile_is_false`. The samples show which event type was dropped and for which distinct IDs.
2. Find where `$process_person_profile: false` gets attached — SDK config, a shared capture wrapper, or the callsite itself.

## Fix

Decide which intent is real:

- **You want person profiles for identified users** → use `person_profiles: 'identified_only'` (posthog-js) instead of `'never'`; identity events then process persons while plain events stay anonymous until identify.
- **You truly want no person processing** → stop calling `identify`/`alias`/`group` at all; they can't work in that mode.
- **A wrapper stamps the flag on everything** → exempt the identity events (`$identify`, `$create_alias`, `$groupidentify`) from it.

## Verify

Re-run the login/group flow, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences — and confirm persons/groups update again.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-invalid-process-person-profile` — the sibling warning: the flag value itself is malformed.
