---
name: fixing-event-dropped-too-old
description: >
  Diagnoses and resolves the `event_dropped_too_old` ingestion warning — an event with a valid timestamp was dropped because it is older than the team's configured `drop_events_older_than` threshold.
  Use when a user asks why old or offline events are missing, why a historical import didn't land, or when `posthog:ingestion-warnings-list` shows `event_dropped_too_old`.
  Covers when the drop is working as intended vs. silently discarding legitimate data (mobile offline queues, imports, clock skew), and how to adjust the team setting.
---

# Fixing `event_dropped_too_old`

An event was **dropped by policy**: its timestamp is valid but older than the team's configured `drop_events_older_than` threshold.
Category `event`, severity `info`: this is an intentional, team-configured drop — the question is whether the configuration matches reality.

## Working as intended, or silent data loss?

The threshold exists to keep stale or replayed data from skewing analytics. The drop is **correct** when what's arriving really is junk (replayed traffic, a runaway retry loop resending week-old batches).

It's **silent data loss** when legitimate late data hits a too-tight threshold:

- **Mobile offline queues** — the biggest trap. Mobile SDKs buffer events while offline and flush when connectivity returns; a user coming back from a flight or weekend legitimately delivers **days-old** events. A threshold measured in hours quietly deletes real user activity, biased against exactly the users with patchy connectivity.
- **Historical imports/backfills** — events carry their original timestamps and get dropped wholesale if the threshold is active during the import.
- **Client clock skew** — a device with a badly wrong clock makes fresh events look old.

## Diagnose

1. `posthog:ingestion-warnings-list` with `type: event_dropped_too_old`. Sample details carry the event name, `distinctId`, `eventTimestamp`, `ageInSeconds`, and `dropThresholdSeconds` — so you can see exactly how late the data was and what the bar is.
2. Read the pattern:
   - A **burst** around one time window with one event family → an import or replayed batch.
   - A **steady trickle** with ages of hours-to-days, from mobile platforms (check `$lib` on the affected persons' other events) → offline queues being deleted.
   - Ages that are absurd (years) or negative-looking → client clock problems, not genuinely old data.

## Fix

The threshold is a **team-wide setting** (`drop_events_older_than`, minimum 1 hour, empty = no restriction — read the current value with `posthog:project-get`, change it via `posthog:project-settings-update` or project settings in the UI). Changing it affects all ingestion for the project — **propose the change to the user and let them decide**, don't adjust it on your own:

- **Mobile offline traffic being dropped** → recommend raising the threshold to cover realistic offline windows (think days, not hours), or clearing it if stale-data protection isn't actually needed.
- **Historical import** → propose temporarily clearing the threshold, running the import, then restoring it.
- **Genuine junk being dropped** → nothing to fix; the setting is doing its job. Say so.
- **Clock skew** → fix the client's time source, or omit custom timestamps and let the SDK stamp them.

Dropped events are gone — an import that ran into the threshold must be re-run after the setting change.

## Verify

Re-run the flow or import, then re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences (for mobile, judge over several days, since offline flushes are sporadic) — and confirm the late events now appear with their original timestamps.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-ignored-invalid-timestamp` — the other timestamp surprise: _unparseable_ timestamps, kept at server time instead of dropped.
