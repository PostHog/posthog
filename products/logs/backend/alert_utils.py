from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

# How often the Temporal schedule fires. Drives shard granularity in
# `compute_shard_offset_seconds` — schedule fires every N seconds, so a
# cadence of M seconds has `M // N` shard slots available.
SCHEDULE_INTERVAL_SECONDS = 60


def compute_shard_offset_seconds(alert_id: UUID, check_interval_minutes: int) -> int:
    """Deterministic per-alert offset within the cadence period.

    Spreads alerts across `cadence / SCHEDULE_INTERVAL_SECONDS` slots so cron
    fires pick up roughly equal slices instead of the whole fleet at once. With
    `SCHEDULE_INTERVAL_SECONDS=60` and a 5-min cadence, alerts distribute over
    5 buckets at offsets [0, 60, 120, 180, 240] seconds.

    `alert_id.int` is stable across pod restarts (process-local `hash()` is not).
    For UUIDv7 IDs, the low bits are the random portion — the modulus operation
    naturally lands on those bits, so distribution is uniform.
    Cadences ≤ schedule interval get 1 shard (no spread possible).
    """
    cadence_seconds = check_interval_minutes * 60
    shard_count = max(1, cadence_seconds // SCHEDULE_INTERVAL_SECONDS)
    shard_index = alert_id.int % shard_count
    return shard_index * SCHEDULE_INTERVAL_SECONDS


def advance_next_check_at(
    current_next_check_at: datetime | None,
    check_interval_minutes: int,
    now: datetime,
    *,
    shard_offset_seconds: int = 0,
) -> datetime:
    """Schedule-relative advancement, snapped to the canonical cadence grid.

    The scheduler cron fires every minute. A sub-minute offset on the returned
    `next_check_at` (e.g. 12:05:30) makes the cron skip a full tick waiting for
    it — the alert is picked up at 12:06:00, ~30s late, every cycle. Snapping
    to the cadence grid (every 5-min alert lands on :00/:05/:10/..., every
    10-min on :00/:10/:20/..., etc.) eliminates that lag AND aligns every alert
    sharing a cadence onto the same canonical grid regardless of when it was
    created.

    `shard_offset_seconds` shifts the canonical grid per-alert to spread load
    across cron fires (see `compute_shard_offset_seconds`). With offset=120 and
    a 5-min cadence, the alert lands on :02/:07/:12/... instead of :00/:05/:10.
    Default 0 = no shard, alert sits on the canonical grid.

    Any drifted `next_check_at` — sub-minute drift OR minute-level offset (e.g.
    legacy alerts on a per-creation-time grid) — self-heals to canonical on its
    next return. Existing alerts heal lazily, one transient short-gap each (the
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
    snapped = _floor_to_cadence_grid(next_at, check_interval_minutes) + timedelta(seconds=shard_offset_seconds)
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
