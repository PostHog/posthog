---
name: fixing-event-dropped-by-transformation
description: >
  Diagnoses and resolves the `event_dropped_by_transformation` ingestion warning — a transformation the team configured returned null and dropped the event.
  Use when a user asks why specific events are missing while others arrive, whether a transformation is eating events, or when `posthog:ingestion-warnings-list` shows `event_dropped_by_transformation`.
  Covers telling intentional filtering from an over-broad filter, and reviewing the named transformation.
---

# Fixing `event_dropped_by_transformation`

A **transformation configured by the team** (Data pipelines → Transformations) processed the event and dropped it.
Category `transformation`, severity `info`: PostHog did exactly what the team's own configuration asked — the question is whether that configuration matches intent.

## Working as intended, or an over-broad filter?

Transformations drop events on purpose all the time — bot filtering, internal-traffic exclusion, PII scrubbing gone nuclear. The warning exists to make that visible, because from the SDK's side dropped events look identical to delivered ones.

It becomes a problem when:

- the transformation's **filter is broader than intended** (a greedy regex, a missing condition, a property match that also catches production traffic),
- the transformation's code hits an unexpected input shape and drops instead of passing through,
- one team's cleanup transformation eats events another team depends on.

## Diagnose

1. `posthog:ingestion-warnings-list` with `type: event_dropped_by_transformation`. The sample details name the exact `transformationId` and `transformationName` plus the dropped `event` and `distinctId` — no guessing which transformation did it. Warnings are debounced per transformation, so each entry represents a stream of drops, not one.
2. Compare what's being dropped against the transformation's purpose: open the named transformation (`posthog:cdp-functions-list` to find it by the name in the details, or Data pipelines → Transformations in the UI) and read its filters and source; `posthog:cdp-functions-logs-retrieve` shows its recent execution logs. Ask "should a `<event name>` from `<this kind of user>` match this?"
3. Check the volume: the warning count and sparkline show how much the transformation eats and since when — a sudden onset usually pinpoints the edit that broadened the filter (`posthog:advanced-activity-logs-list` scoped to the transformation shows who changed what, when).

## Fix

The transformation is team-owned configuration — **propose the change and let the user decide**, since edits affect all matching ingestion from that point on:

- **Intended drops** (bots, internal traffic): nothing to fix; tell the user the warning is their own filter working, and how much it drops.
- **Over-broad filter**: tighten the transformation's filters or code so the unintended events pass through; keep the intended drops.
- **Shouldn't drop at all**: disable the transformation or remove its drop branch.

Dropped events are gone — fixing the filter restores the flow from now on, it doesn't recover history.

## Verify

Re-run the affected flow, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — the drop count for that transformation should fall to just the intended matches — and confirm the previously-missing events arrive while known-junk (bots, internal traffic) is still dropped.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
