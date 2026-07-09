---
name: fixing-cannot-merge-with-illegal-distinct-id
description: >
  Diagnoses and fixes the `cannot_merge_with_illegal_distinct_id` ingestion warning — an `identify`/`alias` call used a placeholder value (`undefined`, `null`, `[object Object]`, `anonymous`, …) as a distinct ID, so PostHog refused the merge.
  Use when a user asks why identify or alias isn't linking users, why a person named "undefined" exists, or when `posthog:ingestion-warnings-list` shows `cannot_merge_with_illegal_distinct_id`.
---

# Fixing `cannot_merge_with_illegal_distinct_id`

An `$identify` or `$create_alias` call used a **placeholder value as a distinct ID** — one of PostHog's blocklisted junk IDs like `undefined`, `null`, `NaN`, `[object Object]`, `true`, `false`, `anonymous`, `guest`, or `distinct_id` itself.
PostHog refuses the merge: if it didn't, every user whose code hit the same bug would merge into one giant "undefined" person.
Category `merge`, severity `warning`: the merge silently didn't happen — the SDK call returned success.

## What it means in your code

A variable was unset at the callsite and got stringified into the ID. The classics:

- `posthog.identify(user.id)` where `user` is not yet loaded → `identify(undefined)` → `"undefined"`.
- `posthog.alias(String(session.userId))` with a missing field → `"undefined"` / `"null"`.
- An object passed where a string was expected → `"[object Object]"`.
- A hardcoded fallback like `"anonymous"` or `"guest"` used as the ID for logged-out users — don't; PostHog already handles anonymous users with its own IDs.

## Diagnose

1. `posthog:ingestion-warnings-list` with `type: cannot_merge_with_illegal_distinct_id`. Each sample's details show `illegalDistinctId` (the junk value — it tells you the bug type: `undefined` = unset variable, `[object Object]` = wrong type) and `otherDistinctId` (the real user it tried to link).
2. Find the callsite: grep the app for `identify(`/`alias(` and trace where the ID argument can be undefined — typically a race with auth state (identify called before the user object resolves).

## Fix

Guard every `identify`/`alias` call so it can only run with a real ID:

```js
if (user?.id) {
  posthog.identify(user.id)
}
```

- Call `identify` after authentication resolves (in the auth callback/effect), not on page load.
- Never use fallback IDs for logged-out users — leave them anonymous; PostHog links the sessions when `identify` eventually runs.
- Type the helper so an object can't be passed as the ID.

## Verify

Re-run the login flow, then re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences. Warnings are debounced; judge by absence of new ones, not shrinking history.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-cannot-merge-already-identified` — the sibling merge refusal; broken identify flows often produce both.
