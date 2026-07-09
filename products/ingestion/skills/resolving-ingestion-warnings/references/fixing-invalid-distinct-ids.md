# Fixing the invalid distinct ID warnings

Both warnings are the same bug class: **something that isn't a user identifier reached the distinct ID argument.** The value's shape decides which warning fires:

| Type                                    | Severity | The junk value                                                                                                                    | What happened                                                                                                                                                                          |
| --------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cannot_merge_with_illegal_distinct_id` | warning  | A blocklisted placeholder: `undefined`, `null`, `NaN`, `[object Object]`, `true`, `false`, `anonymous`, `guest`, `distinct_id`, … | The `identify`/`alias` merge was **refused** — silently; the SDK call returned success. (If it weren't, every user hitting the same bug would merge into one giant "undefined" person) |
| `skipping_event_invalid_distinct_id`    | error    | Anything over 400 characters — a JWT, a serialized object, a URL, a concatenation bug                                             | The event was **dropped** entirely. Every event sent with that value is silently lost until fixed                                                                                      |

## What it means in your code

- `posthog.identify(user.id)` where `user` is not yet loaded → `identify(undefined)` → `"undefined"`.
- `posthog.alias(String(session.userId))` with a missing field → `"undefined"` / `"null"`; an object passed where a string was expected → `"[object Object]"`.
- A token or payload flowing into the ID argument (dots and base64 → a JWT; braces → serialized JSON).
- A hardcoded fallback like `"anonymous"` or `"guest"` for logged-out users — don't; PostHog already handles anonymous users with its own IDs.

## Diagnose

1. `posthog:ingestion-warnings-list` with either `type`. The samples do most of the work: `illegalDistinctId` shows the placeholder (plus `otherDistinctId`, the real user it tried to link); the oversized variant shows the truncated `distinctId` and its length. The value's shape names the bug.
2. Find the callsite: grep the app for `identify(`, `alias(`, and `capture(` with an explicit `distinctId` — and trace where the argument can be undefined (typically a race with auth state) or receive a token/object.

## Fix

Guard every call so only a real, stable user identifier can reach the ID argument:

```js
if (user?.id) {
  posthog.identify(user.id)
}
```

- Call `identify` after authentication resolves (auth callback/effect), not on page load.
- Never use fallback IDs for logged-out users — leave them anonymous; PostHog links the sessions when `identify` eventually runs.
- Type the helper so objects and tokens can't be passed as the ID.

## Verify

Re-run the login/affected flow, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences of either type — and confirm events arrive under the correct persons.

## Related

- [fixing-cannot-merge-already-identified.md](fixing-cannot-merge-already-identified.md) — the other merge refusal; broken identify flows often produce both.
- [fixing-merge-race-condition.md](fixing-merge-race-condition.md) — app-specific shared values (org slugs, tenant names) slip past the placeholder blocklist and build "mega persons" instead.
