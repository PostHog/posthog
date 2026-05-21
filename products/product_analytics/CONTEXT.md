# Product analytics

Insights built on event data — trends, funnels, retention, paths, stickiness, lifecycle. This context covers the language used across these insight types and their query runners.

## Language

### Retention

**Retention insight**:
An insight that tracks how many actors who performed a _start event_ within a period later perform a _return event_ in subsequent periods.
_Avoid_: cohort retention (we already use "cohort" to mean a saved set of users)

**Start event**:
The event (or data warehouse row) that places an actor into a retention cohort for a given period.
_Avoid_: target event, anchor event, cohorting event

**Return event**:
The event (or data warehouse row) that counts an actor as retained in a later period.
_Avoid_: returning event, retention event

**Strict-calendar-date retention**:
The default retention time mode. Intervals are aligned to calendar boundaries — start of day, start of week, start of month. Driven by `timeWindowMode == "strict_calendar_dates"`. Implemented by `RetentionFixedIntervalBaseQueryBuilder`.
_Avoid_: fixed-interval retention (the class name only — confusing because the user-visible mode is "calendar dates"), default retention

**24-hour-window retention**:
The alternative retention time mode. Intervals are 24-hour windows anchored to each actor's first qualifying start event (`t_0`), regardless of calendar boundaries. Driven by `timeWindowMode == "24_hour_windows"`. Implemented by `RetentionRollingIntervalBaseQueryBuilder`.
_Avoid_: rolling-interval retention (the class name only — "rolling" is also used informally to describe how retention itself rolls over time), rolling retention

### Flagged ambiguities

- **"Rolling" is overloaded in this codebase.** `RetentionRollingIntervalBaseQueryBuilder` does _not_ implement "rolling retention" in the general sense — it implements the 24-hour-window time mode only. Use **24-hour-window retention** to refer to the mode; only use "rolling interval" when discussing the class name itself.
- **"Fixed interval" is misleading.** `RetentionFixedIntervalBaseQueryBuilder` handles the strict-calendar-date mode, which is the _default_ and most common path — not a special "fixed" alternative. Use **strict-calendar-date retention** when discussing behavior; reserve "fixed interval" for the class name.

### Data warehouse

**Data warehouse series**:
A start or return event sourced from a data warehouse table rather than the `events` table. Identified by `entity.type == EntityType.DATA_WAREHOUSE`.
_Avoid_: DW series, warehouse event (the row isn't an event)

**DWH variant**:
The data-warehouse-capable base-query implementation that lives alongside the legacy events-only path during the parity rollout. Currently exists for strict-calendar-date retention only (`RetentionFixedIntervalBaseQueryBuilder.build_base_query_dwh`).
_Avoid_: new query, v2 query

**Parity gap**:
A query shape where the DWH variant does not yet produce results identical to the legacy events-only path. Tracked in `_query_uses_known_retention_base_query_variant_gap`.

## Example dialogue

> **Dev:** "Customer is on 24-hour-window retention with a Stripe table as the return event — does that work?"
>
> **Domain:** "Today no — the DWH variant only exists for strict-calendar-date retention. 24-hour-window retention runs through `RetentionRollingIntervalBaseQueryBuilder`, which has no data warehouse series support yet."
>
> **Dev:** "So if I want a Stripe-table return, the user has to pick strict calendar dates?"
>
> **Domain:** "Right. And once we retrofit 24-hour-window retention for data warehouse series, that constraint drops — there's no separate variant flag for that path, the retrofit goes directly."
