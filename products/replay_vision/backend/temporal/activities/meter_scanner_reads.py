import datetime as dt
from uuid import UUID

from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.read_meter_types import MeterScannerReadsResult

# Re-scan the last two full hours plus the current partial one. Buckets overwrite per hour key, so
# the overlap with the previous run never double-counts, and a late-flushing query_log entry still
# lands in its (re-scanned, complete) hour bucket.
_FULL_HOURS_RESCANNED = 2

_READ_BYTES_BY_SCANNER_HOUR_SQL = """
SELECT
    JSONExtractString(log_comment, 'scanner_id') AS scanner_id,
    toStartOfHour(toTimeZone(event_time, 'UTC')) AS hour,
    sum(read_bytes) AS read_bytes
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
        {"cluster": settings.CLICKHOUSE_CLUSTER, "since": since},
        workload=Workload.OFFLINE,
        settings={"max_execution_time": 120, "skip_unavailable_shards": 1},
    )

    by_scanner: dict[str, dict[str, int]] = {}
    for scanner_id, hour, read_bytes in rows:
        # The tag is a free-form string in the query log, so a junk value must not take the run down.
        if not _is_uuid(scanner_id):
            continue
        by_scanner.setdefault(scanner_id, {})[hour.replace(tzinfo=dt.UTC).isoformat()] = int(read_bytes)

    prune_cutoff = now - dt.timedelta(hours=25)
    scanners = list(ReplayScanner.objects.filter(pk__in=by_scanner.keys()).only("id", "sweep_read_bytes_by_hour"))
    for scanner in scanners:
        buckets = dict(scanner.sweep_read_bytes_by_hour or {})
        buckets.update(by_scanner[str(scanner.id)])
        fresh = {}
        for hour_iso, read_bytes in buckets.items():
            hour = _parse_hour(hour_iso)
            if hour is not None and hour >= prune_cutoff:
                fresh[hour_iso] = read_bytes
        scanner.sweep_read_bytes_by_hour = fresh
    # One statement per batch rather than per scanner: this runs hourly over every active scanner.
    ReplayScanner.objects.bulk_update(scanners, ["sweep_read_bytes_by_hour"], batch_size=500)

    activity.logger.info("replay_vision.read_meter_updated", extra={"scanners": len(scanners)})
    return MeterScannerReadsResult(scanners_updated=len(scanners))


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _parse_hour(hour_iso: str) -> dt.datetime | None:
    """Parse a bucket key, treating a naive value as UTC so comparisons cannot raise."""
    try:
        hour = dt.datetime.fromisoformat(hour_iso)
    except (TypeError, ValueError):
        return None
    return hour if hour.tzinfo is not None else hour.replace(tzinfo=dt.UTC)
