from __future__ import annotations

from datetime import datetime, timedelta


def advance_next_check_at(
    current_next_check_at: datetime | None,
    check_interval_minutes: int,
    now: datetime,
) -> datetime:
    """Schedule-relative advancement, snapped to the canonical cadence grid.

    The scheduler cron fires every minute. A sub-minute offset on the returned
    NCA (e.g. 12:05:30) makes the cron skip a full tick waiting for it — the
    alert is picked up at 12:06:00, ~30s late, every cycle. Snapping to the
    cadence grid (every 5-min alert lands on :00/:05/:10/..., every 10-min on
    :00/:10/:20/..., etc.) eliminates that lag AND aligns every alert sharing
    a cadence onto the same canonical grid regardless of when it was created.

    Any drifted NCA — sub-minute drift OR minute-level offset (e.g. legacy
    alerts on a per-creation-time grid) — self-heals to canonical on its next
    return. Existing alerts heal lazily, one transient short-gap each (the
    state machine handles the brief overlap window via N-of-M dedup).

    Inter-eval gaps are exactly `check_interval_minutes` in steady state. The
    only "shorter than cadence" gaps are (1) creation-to-first-eval and (2)
    the one-time heal cycle for a previously-drifted alert. Both are
    cosmetic — alert eval windows tile correctly because they're anchored
    on `date_to`, not on prior eval time.
    """
    if check_interval_minutes <= 0:
        raise ValueError(f"check_interval_minutes must be positive, got {check_interval_minutes}")
    interval = timedelta(minutes=check_interval_minutes)

    if current_next_check_at is None:
        next_at = now + interval
    else:
        next_at = current_next_check_at + interval
        if next_at <= now:
            elapsed = (now - next_at).total_seconds()
            intervals_to_skip = int(elapsed // interval.total_seconds()) + 1
            next_at += interval * intervals_to_skip

    # Bump by full interval (not 1 cadence-grid slot upward) when the floor
    # lands at/before `now`, so the alert stays on its canonical cadence grid.
    snapped = _floor_to_cadence_grid(next_at, check_interval_minutes)
    if snapped <= now:
        snapped += interval
    return snapped


def _floor_to_cadence_grid(t: datetime, cadence_minutes: int) -> datetime:
    """Floor to the previous cadence-grid slot, anchored at midnight of `t`.

    For divisors of 60 (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60), this is
    "every cadence minutes within the hour" — the grid an operator expects
    (5-min alerts on :00/:05/:10, 15-min on :00/:15/:30/:45, etc.). Cadences
    > 60 that divide 1440 (90, 120, 240, 360, 480, 720, 1440) also tile
    cleanly. Cadences that divide neither 60 nor 1440 (e.g. 7, 11, 100) get
    a discontinuity at midnight where the grid re-anchors — fine in practice
    because alert UI almost certainly constrains cadence to common values.
    """
    total_minutes = t.hour * 60 + t.minute
    floored_minutes = (total_minutes // cadence_minutes) * cadence_minutes
    return t.replace(hour=floored_minutes // 60, minute=floored_minutes % 60, second=0, microsecond=0)
