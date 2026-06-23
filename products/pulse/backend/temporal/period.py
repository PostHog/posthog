"""Deterministic period keys for Pulse scans — find-or-create digests per (team, period)."""

import datetime as dt

from products.pulse.backend.models import PulseSubscriptionFrequency


def period_key(now: dt.datetime, frequency: PulseSubscriptionFrequency | str) -> str:
    """Stable identifier for the scan period containing `now`.

    Weekly -> ISO week ("2026-W22"); daily -> date ("2026-05-29"). Used as the
    idempotency key so re-runs and Temporal retries reuse one digest per period.
    Caller passes a deterministic clock (`workflow.now()`) inside workflows.
    """
    if frequency == PulseSubscriptionFrequency.DAILY:
        return now.date().isoformat()
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def period_bounds(now: dt.datetime, frequency: PulseSubscriptionFrequency | str) -> tuple[dt.datetime, dt.datetime]:
    """(`period_start`, `period_end`) for the digest, snapped to the period boundary — the last
    completed period. Daily -> the prior calendar day [00:00, 00:00); weekly -> the prior ISO week
    [Mon 00:00, Mon 00:00).

    Snapping makes the bounds a pure function of the period rather than of the exact `now`, so every
    run within one `period_key` yields identical bounds. `create_or_get_digest_activity` matches its
    find-or-create on these bounds, so they must not vary with the calling instant — otherwise a
    manual run overlapping a scheduled one in the same period would create a duplicate digest.
    """
    if frequency == PulseSubscriptionFrequency.DAILY:
        anchor = dt.datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
        return anchor - dt.timedelta(days=1), anchor
    monday = now - dt.timedelta(days=now.weekday())
    anchor = dt.datetime(monday.year, monday.month, monday.day, tzinfo=now.tzinfo)
    return anchor - dt.timedelta(days=7), anchor
