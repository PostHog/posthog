---
name: fixing-process-person-profile-warnings
description: >
  Diagnoses and fixes the two `$process_person_profile` ingestion warnings — `invalid_process_person_profile` (non-boolean value, silently ignored and defaulted to true) and `invalid_event_when_process_person_profile_is_false` (`$identify`/`$create_alias`/`$merge_dangerously`/`$groupidentify` dropped because the event disabled person processing).
  Use when a user asks why person profiles are created despite opting out, why anonymous-event settings aren't taking effect, why identify or group calls have no effect, or when `posthog:ingestion-warnings-list` shows either type.
---

# Fixing the `$process_person_profile` warnings

`$process_person_profile: false` marks an event as anonymous — cheaper, no person profile. Two different mistakes around that flag produce two warnings:

| Type                                                 | Severity | What happened                                                                                                                                                                        |
| ---------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `invalid_process_person_profile`                     | warning  | The value wasn't a boolean (`"false"`, `"yes"`, `0`, …) — PostHog **ignored it and defaulted to `true`**. The event was ingested and person processing ran anyway                    |
| `invalid_event_when_process_person_profile_is_false` | error    | An `$identify`/`$create_alias`/`$merge_dangerously`/`$groupidentify` carried a valid `false` — but these operations exist to modify person/group state, so the event was **dropped** |

Both failure modes are silent from the SDK's side. The first quietly opts you back **into** person processing (and its cost); the second makes identity operations no-ops.

## Diagnose

1. `posthog:ingestion-warnings-list` with either `type`. For the non-boolean variant, the sample details show the exact value received — its type names the bug (`"false"` = stringified config/env value, `0` = numeric flag). For the dropped variant, the samples show which identity event was dropped and for which distinct IDs.
2. Find where the flag gets attached: SDK config, a shared capture wrapper, or the callsite. Env vars and JSON configs are the usual source of stringified booleans; a global "mark everything anonymous" wrapper is the usual source of the identity-event contradiction.

## Fix

Decide which intent is real, then make the flag match it:

- **Pass a real boolean** — parse config values (`value === 'true'`) before they reach the SDK; never send `"false"`.
- **You want person profiles for identified users** → in posthog-js use the supported config, `person_profiles: 'identified_only'`, instead of hand-setting the property per event or using `'never'` — identity events then process persons while plain events stay anonymous until identify.
- **A wrapper stamps `false` on everything** → exempt the identity events (`$identify`, `$create_alias`, `$groupidentify`) from it.
- **You truly want no person processing** → stop calling `identify`/`alias`/`group` at all; they cannot work in that mode.

## Verify

Re-run the flow, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences of either type — and confirm the intended behavior: anonymous events stop creating person profiles, and persons/groups update again where they should.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
