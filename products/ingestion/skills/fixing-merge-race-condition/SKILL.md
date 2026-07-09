---
name: fixing-merge-race-condition
description: >
  Diagnoses and fixes the `merge_race_condition` ingestion warning — concurrent merge operations collided on the same persons, so one merge attempt was abandoned.
  Use when a user asks why identified users intermittently show up as separate or duplicate persons, or when `posthog:ingestion-warnings-list` shows `merge_race_condition`.
  Covers where the concurrency comes from (identify-per-request patterns, parallel workers, retry storms), the "mega person" magnet check, and how to deduplicate identity calls.
---

# Fixing `merge_race_condition`

Too many **concurrent merge operations hit the same persons at once**, and PostHog abandoned one of them to protect consistency.
Category `merge`, severity `error`: the event kept flowing, but **that merge did not persist** — the two persons stay separate until a later, uncontended identify/alias succeeds.

Unlike most warnings this one is **never debounced** — every occurrence lands, so the count is a true measure of how much merge contention the app generates.

## What it means in your code

A single user's identity operations should be rare — once per login/signup. Contention on one person pair means something fires `identify`/`alias` for the same user **in parallel**:

- `identify()` called on every request, page load, or render instead of once per session — a burst of parallel calls races itself.
- Parallel backend workers or batch jobs identifying the same users simultaneously (a user-sync fan-out where multiple shards touch the same account).
- Retry storms: a failed capture batch re-sent while the original is still processing.
- **A "mega person" acting as a merge magnet**: a bug identifies many different humans with the same value (an org ID, a tenant name, a default/placeholder), funneling them all into one person. That person becomes party to everyone's merges — contention concentrates on it structurally, no matter how well-behaved each individual client is.
- Several devices/tabs of the same user logging in at the same moment is normal in small doses — steady high counts are the code smell.

## Diagnose

1. `posthog:ingestion-warnings-list` with `type: merge_race_condition`. Sample details carry both sides (`sourcePersonDistinctId`, `targetPersonDistinctId`, the person UUIDs) and the triggering `event_uuid`.
2. **Check for a mega person first**: resolve the sampled distinct IDs to persons and count each person's distinct IDs (`posthog:persons-list`, or `posthog:execute-sql` against the person-distinct-ID mapping). A person with hundreds or thousands of distinct IDs is a merge magnet — the race warnings are a symptom, and the real bug is whatever shared value keeps getting passed to `identify` (look at the person's distinct ID list: an org slug, `"user"`, an email domain, a device model repeating tells you exactly which value leaked in).
3. Measure the shape: a handful of scattered occurrences is benign concurrency; sustained counts or bursts around specific times point at a code path (deploy jobs, login storms, a sync cron).
4. Find the caller: query the events table (`posthog:execute-sql`) for `$identify`/`$create_alias` events for the affected distinct IDs and look at their frequency and spacing — dozens of identifies per user per minute means an identify-per-request pattern; bursts at fixed times mean a batch job.
5. Confirm the aftermath: check whether the persons eventually merged (a later identify usually wins once contention stops). If they're still separate, the split analytics will persist until one more identify for that pair goes through.

## Fix

Reduce the contention at its source:

- **Mega person**: fix the identify callsite passing the shared value — each `identify` must receive an ID unique to one human. The already-merged mega person is damage that code can't cleanly undo; surface it to the user and recommend contacting PostHog support about splitting it rather than attempting programmatic repair.
- **Frontend**: call `identify` once when auth state changes (login/signup callback), not per request, per page, or per render. Guard with "already identified as this user?" checks where the SDK doesn't already.
- **Backend**: route identity operations for a given user through a single path — dedupe by user ID (idempotency key, per-user lock, or partition-by-user in workers) so parallel jobs can't race on the same person.
- **Retries**: don't blind-resend identify batches; make retries idempotent and spaced.

No PostHog-side setting needs changing — the protection is doing its job; the app is supplying the race.

## Verify

Re-run the flow, then re-query `posthog:ingestion-warnings-list` with a post-fix `since` — counts should drop to the occasional benign collision (multiple devices logging in simultaneously) or zero. Confirm previously-affected users resolve to a single person, and that no person's distinct ID count keeps climbing.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-cannot-merge-already-identified` — the deterministic merge refusal; identify-per-request patterns often produce both warnings.
- `fixing-cannot-merge-with-illegal-distinct-id` — PostHog's blocklist catches common placeholder IDs, but app-specific shared values (org slugs, tenant names) slip past it and build mega persons instead.
