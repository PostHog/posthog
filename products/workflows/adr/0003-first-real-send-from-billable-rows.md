# The success event comes from a daily task over billable rows

`workflow first real send` is captured by a daily Celery task that finds each workflow's first billable email in `app_metrics2` and marks it once on `HogFlow.first_real_send_at`, not by the send path.
The send path runs in the Node CDP workers on every message, and a once-per-workflow check there would add a lookup to the hot path for an event that only needs day-level freshness.
We considered reading the usage report as a data warehouse metric instead, but it is per team, so it loses the workflow and its attempt ID.
The task covers every new workflow, with or without an attempt, so Experiments can compare first sends across every arm, the holdout included.

## Consequences

The event arrives up to a day after the send, with the send's time on the column.
The task sets the column before it captures, so a rerun never captures twice, and a failed capture loses one event but not the date.
Whether sends from the PostHog test sender write billable rows is open; if they do, the task skips workflows that send only through it.
See `docs/architecture/messaging-cta-slot.md`.
