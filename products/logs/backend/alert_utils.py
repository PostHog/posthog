from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID

from django.db.models import Q

from products.alerts.backend.scheduling import (
    advance_next_check_at,
    compute_shard_offset_seconds as shared_compute_shard_offset_seconds,
)

__all__ = [
    "HOIST_BATCHED_ALERT_PREDICATES",
    "MAX_BYTES_TO_READ",
    "SCHEDULE_INTERVAL_SECONDS",
    "advance_next_check_at",
    "compute_shard_offset_seconds",
    "due_alerts_q",
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

# Hoists the OR of per-alert predicates into the batched alert query's outer
# WHERE so ClickHouse can prune the scan with them. Results are identical
# either way; the flag changes only how much data each check reads. Default
# off for a staged rollout, because a planner regression on the hoisted shape
# (e.g. pathological KeyCondition analysis on a large OR chain) would hit
# every batched check at once: enable per environment with
# LOGS_ALERTING_HOIST_BATCHED_ALERT_PREDICATES=1, then flip this default once
# both regions have soaked.
HOIST_BATCHED_ALERT_PREDICATES = os.environ.get("LOGS_ALERTING_HOIST_BATCHED_ALERT_PREDICATES", "0") == "1"


def compute_shard_offset_seconds(alert_id: UUID, check_interval_minutes: int) -> int:
    return shared_compute_shard_offset_seconds(
        alert_id,
        check_interval_minutes,
        schedule_interval_seconds=SCHEDULE_INTERVAL_SECONDS,
    )


def due_alerts_q(now: datetime, *, broken_state: str, snoozed_state: str) -> Q:
    return (
        Q(enabled=True)
        & (Q(next_check_at__lte=now) | Q(next_check_at__isnull=True))
        & ~Q(state=broken_state)
        & ~Q(state=snoozed_state, snooze_until__gt=now)
    )
