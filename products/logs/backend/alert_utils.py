from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.db.models import Q

import structlog

from products.alerts.backend.scheduling import (
    advance_next_check_at,
    compute_shard_offset_seconds as shared_compute_shard_offset_seconds,
    parse_blocked_windows_tuples,
    scan_next_unblocked_utc,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "MAX_BYTES_TO_READ",
    "SCHEDULE_INTERVAL_SECONDS",
    "advance_next_check_at",
    "compute_shard_offset_seconds",
    "due_alerts_q",
    "next_allowed_check_at",
]

# How often the Temporal schedule fires. Drives shard granularity in
# `compute_shard_offset_seconds`: schedule fires every N seconds, so a
# cadence of M seconds has `M // N` shard slots available.
SCHEDULE_INTERVAL_SECONDS = 60

# Per-query CH read cap (bytes). Cohort chunking (`MAX_ALERT_COHORT_SIZE`) keeps reads
# bounded at the source; this is the safety net if a chunk surprises us. Tunable via env
# so we can bump for customers whose filters genuinely need more headroom without
# redeploying. Aligns to CH's GiB-based reporting (1024^3) so the value here matches
# the "max bytes: N GiB" in CH error messages. Default 5 GiB (5,368,709,120).
# Lives here, not in `temporal/constants.py`, because `alert_check_query.py` (the
# consumer) is outside the temporal package. Importing it from temporal would create
# a circular import via `temporal/__init__.py` to activities to alert_check_query.
MAX_BYTES_TO_READ = int(os.environ.get("LOGS_ALERTING_MAX_BYTES_TO_READ", "5368709120"))


def compute_shard_offset_seconds(alert_id: UUID, check_interval_minutes: int) -> int:
    return shared_compute_shard_offset_seconds(
        alert_id,
        check_interval_minutes,
        schedule_interval_seconds=SCHEDULE_INTERVAL_SECONDS,
    )


def next_allowed_check_at(
    candidate: datetime,
    *,
    team_timezone: str,
    schedule_restriction: dict[str, object] | None,
) -> datetime:
    windows = parse_blocked_windows_tuples(schedule_restriction)
    allowed_at = scan_next_unblocked_utc(candidate, team_timezone, windows)
    if allowed_at is not None:
        return allowed_at

    logger.warning(
        "logs_alert.schedule_restriction.next_allowed_check_at_exceeded_cap",
        team_timezone=team_timezone,
    )
    retry_candidate = candidate.astimezone(UTC) + timedelta(days=1)
    allowed_at = scan_next_unblocked_utc(retry_candidate, team_timezone, windows)
    if allowed_at is not None:
        return allowed_at

    logger.error(
        "logs_alert.schedule_restriction.next_allowed_check_at_giving_up_after_retry",
        team_timezone=team_timezone,
    )
    return retry_candidate.replace(second=0, microsecond=0)


def due_alerts_q(now: datetime, *, broken_state: str, snoozed_state: str) -> Q:
    return (
        Q(enabled=True)
        & (Q(next_check_at__lte=now) | Q(next_check_at__isnull=True))
        & ~Q(state=broken_state)
        & ~Q(state=snoozed_state, snooze_until__gt=now)
    )
