---
name: fixing-cannot-merge-already-identified
description: >
  Diagnoses and fixes the `cannot_merge_already_identified` ingestion warning — an `identify`/`alias` call tried to merge two persons that are both already identified, so PostHog refused the merge and the accounts silently stayed separate.
  Use when a user asks why two accounts aren't merging, why events are split across duplicate persons, why identify "doesn't work", or when `posthog:ingestion-warnings-list` shows `cannot_merge_already_identified`.
  Covers how identification and merging work, why the refusal is silent, how to tell a code bug from a duplicate-account situation, and per-SDK fixes.
---

# Fixing `cannot_merge_already_identified`

An `$identify` or `$create_alias` call asked PostHog to merge two persons that are **both already identified**.
PostHog refuses this to protect identity data — merging two established users is destructive and almost always a bug.
Category `merge`, severity `warning`: no data was lost, but **the merge did not happen** and events continue accumulating under two separate persons.

## The critical insight: the refusal is silent

The SDK call succeeds (2xx) — `identify`/`alias` never reports the refusal back.
The only signals are this warning and the symptom: one human, two person profiles, analytics split between them (funnels break, unique-user counts inflate).

## How merging is supposed to work

- A person becomes **identified** the first time `identify(user_id)` links it to an anonymous session.
- `identify` is for linking an _anonymous_ person to a user — exactly once per sign-up/log-in.
- `alias` is for attaching an additional ID to a person _before or at_ identification.
- Merging two _already identified_ persons is never done implicitly — that's what this warning refuses. There is no application-level API that should be doing it.

## Diagnose

1. List the warnings with `posthog:ingestion-warnings-list` (`type: cannot_merge_already_identified`). Each sample's details carry `sourcePersonDistinctId` and `targetPersonDistinctId` — the two sides of the refused merge — plus the `event_uuid` of the triggering call.
2. Resolve **both** distinct IDs to their persons (`posthog:persons-list`) and look at their properties and event history.
3. Decide which situation you're in:
   - **Two different humans** → the code is trying to merge people it shouldn't. Find and fix the callsite (below). This is the common case.
   - **One human with two accounts** (e.g. signed up twice with work and personal email) → the identify/alias code path is only a symptom; the duplicate accounts are the real problem (see below).

## Common causes in code

- `identify()` called on account switching or impersonation with a _different user's_ ID while the device still carries the previous identified session — missing `reset()` on logout is the classic version.
- Two ID schemes for the same human: identifying with an email in one flow and a database ID in another creates two identified persons, and later code tries to link them.
- An admin/support "merge duplicate accounts" feature implemented with `identify`/`alias` — application code cannot join two identified persons, by design.
- Backend jobs calling `identify` with `$anon_distinct_id` set to another user's known distinct ID.

## Fix

Fix the identification flow — don't look for a way to force the merge from application code:

- `identify` only at login/signup, always with the canonical user ID.
- `reset()` on logout, especially on shared devices — the next login must start from a fresh anonymous session.
- Pick ONE canonical ID scheme (a stable user ID, not sometimes-email-sometimes-ID) and use it in every `identify` call, across all platforms and the backend.
- Use `alias` only to attach secondary IDs _before_ the person is identified.
- Remove any application feature that tries to merge two identified users via `identify`/`alias` — it can never work, and the silent refusal makes it look like it does.

If two persons genuinely are the same human and must be joined, that is a **manual, one-off administrative operation** — performed deliberately by a human (and irreversibly joining both event histories) — never something application code does on its own. Confirm both profiles really are the same person before considering it.

## Verify

1. Re-run the login/logout/identify flow.
2. Re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences for those distinct IDs.
3. Check new sessions: events land under a single person per human.

## Related

- `resolving-ingestion-warnings` — the triage entry point covering every warning type.
- `fixing-invalid-distinct-ids` — the sibling refusal, where the distinct ID is a placeholder like `undefined`; often the same broken identify callsite produces both.
