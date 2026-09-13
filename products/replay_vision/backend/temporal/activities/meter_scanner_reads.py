import datetime as dt
from uuid import UUID

from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries.scanner_candidate_query import (
    DEEP_SWEEP_CANDIDATE_QUERY_TYPE,
    FAST_SWEEP_QUERY_TYPES,
)
from products.replay_vision.backend.temporal.constants import DEEP_SPEND_WINDOW_DAYS
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.read_meter_types import MeterScannerReadsResult, parse_bucket_hour

# Re-scan the last two full hours plus the current partial one. Buckets overwrite per hour key, so
# the overlap with the previous run never double-counts, and a late-flushing query_log entry still
# lands in its (re-scanned, complete) hour bucket.
_FULL_HOURS_RESCANNED = 2

_READ_BYTES_BY_SCANNER_HOUR_SQL = """
SELECT
    JSONExtractString(log_comment, 'scanner_id') AS scanner_id,
    toStartOfHour(toTimeZone(event_time, 'UTC')) AS hour,
    sum(read_bytes) AS total_read_bytes,
    sumIf(read_bytes, JSONExtractString(log_comment, 'query_type') = %(deep_query_type)s) AS deep_read_bytes,
    sumIf(read_bytes, JSONExtractString(log_comment, 'query_type') IN %(fast_query_types)s) AS fast_read_bytes
FROM clusterAllReplicas(%(cluster)s, system.query_log)
WHERE event_date >= today() - 1
  AND event_time >= %(since)s
  AND type > 1
  AND is_initial_query
  -- Substring match first so the JSON parsing only runs on this product's rows rather than on
  -- every query the cluster logged.
  AND log_comment LIKE '%%replay_vision%%'
  AND JSONExtractString(log_comment, 'product') = 'replay_vision'
  AND scanner_id != ''
GROUP BY scanner_id, hour
"""


@activity.defn
@track_activity()
def meter_scanner_read_bytes_activity() -> MeterScannerReadsResult:
    """Fold recent per-scanner ClickHouse read bytes from query_log into hour buckets on the scanner rows."""
    from django.conf import settings  # noqa: PLC0415 — Django settings are unavailable at sandbox import time

    now = dt.datetime.now(dt.UTC)
    # Hour-aligned so every scanned hour bucket is covered in full, making the overwrite monotone-correct.
    since = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=_FULL_HOURS_RESCANNED)
    rows = sync_execute(
        _READ_BYTES_BY_SCANNER_HOUR_SQL,
        {
            "cluster": settings.CLICKHOUSE_CLUSTER,
            "since": since,
            "deep_query_type": DEEP_SWEEP_CANDIDATE_QUERY_TYPE,
            "fast_query_types": FAST_SWEEP_QUERY_TYPES,
        },
        workload=Workload.OFFLINE,
        settings={"max_execution_time": 120, "skip_unavailable_shards": 1},
    )

    by_scanner: dict[str, dict[str, tuple[int, int, int]]] = {}
    for scanner_id, hour, total_read_bytes, deep_read_bytes, fast_read_bytes in rows:
        # The tag is a free-form string in the query log, so a junk value must not take the run down.
        if not _is_uuid(scanner_id):
            continue
        hour_iso = hour.replace(tzinfo=dt.UTC).isoformat()
        by_scanner.setdefault(scanner_id, {})[hour_iso] = (
            int(total_read_bytes),
            int(deep_read_bytes),
            int(fast_read_bytes),
        )

    prune_cutoff = now - dt.timedelta(hours=25)
    # Wider than the sweep's: the deep pass is priced on its average over this window, so a bucket
    # pruned at 25h would let a stretched pass age out of its own measurement.
    deep_prune_cutoff = now - dt.timedelta(days=DEEP_SPEND_WINDOW_DAYS)
    scanners = list(
        ReplayScanner.objects.filter(pk__in=by_scanner.keys()).only(
            "id", "sweep_read_bytes_by_hour", "deep_read_bytes_by_hour", "fast_read_bytes_by_hour"
        )
    )
    for scanner in scanners:
        metered = by_scanner[str(scanner.id)]
        scanner.sweep_read_bytes_by_hour = _merged_buckets(
            scanner.sweep_read_bytes_by_hour, {h: total for h, (total, _, _) in metered.items()}, prune_cutoff
        )
        # Zeros are omitted: a missing bucket already reads as no spend, and most scanners never run a
        # deep pass in a given hour, so storing them would double this table's hourly write volume.
        scanner.deep_read_bytes_by_hour = _merged_buckets(
            scanner.deep_read_bytes_by_hour,
            {h: deep for h, (_, deep, _) in metered.items() if deep},
            deep_prune_cutoff,
        )
        scanner.fast_read_bytes_by_hour = _merged_buckets(
            scanner.fast_read_bytes_by_hour, {h: fast for h, (_, _, fast) in metered.items()}, prune_cutoff
        )
    # One statement per batch rather than per scanner: this runs hourly over every active scanner.
    ReplayScanner.objects.bulk_update(
        scanners,
        ["sweep_read_bytes_by_hour", "deep_read_bytes_by_hour", "fast_read_bytes_by_hour"],
        batch_size=500,
    )

    activity.logger.info("replay_vision.read_meter_updated", extra={"scanners": len(scanners)})
    return MeterScannerReadsResult(scanners_updated=len(scanners))


def _merged_buckets(
    existing: dict[str, int] | None, fresh: dict[str, int], prune_cutoff: dt.datetime
) -> dict[str, int]:
    """The callers pass different cutoffs deliberately: the deep bucket must outlive its pricing window."""
    buckets = dict(existing or {})
    buckets.update(fresh)
    return {
        hour_iso: read_bytes
        for hour_iso, read_bytes in buckets.items()
        if (hour := parse_bucket_hour(hour_iso)) is not None and hour >= prune_cutoff
    }


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
