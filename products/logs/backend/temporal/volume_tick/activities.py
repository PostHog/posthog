import time
import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog
import temporalio.activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

from products.logs.backend.temporal.volume_tick.aggregation import RollupPreview, preview_rollup
from products.logs.backend.temporal.volume_tick.constants import (
    BUCKET_MINUTES,
    BUCKET_SECONDS,
    FINALIZATION_ALLOWANCE,
    TEAM_ALLOWLIST,
    TEAMS_WITH_LOGS_WINDOW,
)
from products.logs.backend.temporal.volume_tick.metrics import (
    increment_tick_runs,
    record_clickhouse_duration,
    record_rollup_duration,
    record_rollup_preview,
    record_teams_with_logs,
)

logger = structlog.get_logger(__name__)

# The Temporal activity timeout cannot kill a ClickHouse query already running in
# the thread pool, so without server-side bounds each retry stacks another live
# scan. Timeout stays under half of ACTIVITY_TIMEOUT to leave retry room; the
# bytes cap is ~25x the expected read of the two narrow columns over the window,
# so it only trips on runaway volume, never on organic growth.
_DISCOVERY_QUERY_SETTINGS = {
    "max_execution_time": 25,
    "max_bytes_to_read": 5_000_000_000,
}


# Temporal payload dataclasses stay on the stdlib form (the sibling alerting
# convention); @frozen's kw_only/slots buy nothing across the serialization boundary.
@dataclasses.dataclass(frozen=True)
class VolumeTickInput:
    pass


@dataclasses.dataclass(frozen=True)
class VolumeTickOutput:
    ticked_at: str
    teams_with_logs: int
    minute_shard: int
    teams_due_in_shard: int
    due_bucket_start: str
    due_bucket_end: str
    # None when the allowlist is empty and the rollup query therefore did not run.
    rollup_rows: int | None = None
    source_rows: int | None = None
    distinct_services: int | None = None
    rows_without_namespace: int | None = None
    rows_without_environment: int | None = None


@frozen
class DueBucket:
    start: datetime
    end: datetime


def due_bucket_bounds(now: datetime) -> DueBucket:
    """The most recent 5-minute grid bucket that is due for finalization at `now`:
    the newest bucket whose close is at least FINALIZATION_ALLOWANCE in the past."""
    latest_finalizable_end = now - FINALIZATION_ALLOWANCE
    end_epoch = int(latest_finalizable_end.timestamp()) // BUCKET_SECONDS * BUCKET_SECONDS
    end = datetime.fromtimestamp(end_epoch, tz=UTC)
    return DueBucket(start=end - timedelta(seconds=BUCKET_SECONDS), end=end)


@frozen
class TeamsWithLogs:
    total: int
    due_in_shard: int


def count_teams_with_logs(begin: datetime, end: datetime, shard: int) -> TeamsWithLogs:
    """Distinct teams with at least one log record in [begin, end), and the subset
    whose `team_id % BUCKET_MINUTES` puts them in `shard`.

    Queries the physical `logs_distributed` table, not `logs` — `logs` is the
    HogQL table alias and does not exist for raw `sync_execute` SQL.
    """
    with tags_context(product=Product.LOGS, feature=Feature.PREAGGREGATION):
        rows = sync_execute(
            """
            SELECT
                uniqExact(team_id),
                uniqExactIf(team_id, modulo(team_id, %(shards)s) = %(shard)s)
            FROM logs_distributed
            WHERE timestamp >= %(begin)s AND timestamp < %(end)s
            """,
            {"begin": begin, "end": end, "shards": BUCKET_MINUTES, "shard": shard},
            workload=Workload.LOGS,
            settings=_DISCOVERY_QUERY_SETTINGS,
        )
    return TeamsWithLogs(total=int(rows[0][0]), due_in_shard=int(rows[0][1]))


_count_teams_with_logs_async = database_sync_to_async_pool(count_teams_with_logs)
_preview_rollup_async = database_sync_to_async_pool(preview_rollup)


@frozen
class TimedRollupPreview:
    preview: RollupPreview
    duration_ms: int


def teams_due_in_shard(team_ids: Sequence[int], minute_shard: int) -> list[int]:
    """The allowlisted teams this tick is responsible for.

    A bucket stays due for every minute of the next one, so a tick that ignored the
    shard would run the same scan BUCKET_MINUTES times over. The shard picks the one
    minute each team belongs to, matching the residue the discovery query counts.
    """
    return [team_id for team_id in team_ids if team_id % BUCKET_MINUTES == minute_shard]


async def _preview_due_bucket(due: DueBucket, minute_shard: int) -> TimedRollupPreview | None:
    """Measure the due bucket's rollup for the allowlisted teams in this shard.

    Once the commit protocol lands this becomes the write, where an unsharded read
    would produce duplicate generations rather than merely wasted scans.
    """
    due_teams = teams_due_in_shard(TEAM_ALLOWLIST, minute_shard)
    if not due_teams:
        return None
    started = time.monotonic()
    preview = await _preview_rollup_async(team_ids=due_teams, start=due.start, end=due.end)
    return TimedRollupPreview(preview=preview, duration_ms=int((time.monotonic() - started) * 1000))


@temporalio.activity.defn
async def volume_tick_heartbeat_activity(input: VolumeTickInput) -> VolumeTickOutput:
    # The log volume rollup tick, observing rather than writing: it runs the same
    # scan and grouping the rollup writer will run, and publishes what that write
    # would contain. The write itself needs the commit protocol to make its rows
    # visible, so it lands with that.
    ticked_at = datetime.now(UTC)
    due = due_bucket_bounds(ticked_at)
    # One team cohort per minute of the bucket: the every-minute schedule smears
    # teams across the bucket's minutes, so team_id % BUCKET_MINUTES is the shard.
    minute_shard = ticked_at.minute % BUCKET_MINUTES
    started = time.monotonic()
    try:
        counts = await _count_teams_with_logs_async(ticked_at - TEAMS_WITH_LOGS_WINDOW, ticked_at, minute_shard)
        # Discovery's own duration, measured and recorded before the rollup runs.
        # The two queries differ by an order of magnitude, so one timer covering
        # both reports neither, and recording here keeps discovery latency
        # observable on the ticks whose rollup then fails.
        duration_ms = int((time.monotonic() - started) * 1000)
        record_clickhouse_duration(duration_ms)
        timed = await _preview_due_bucket(due, minute_shard)
    except Exception:
        increment_tick_runs("error")
        raise

    record_teams_with_logs(counts.total)
    if timed is not None:
        record_rollup_duration(timed.duration_ms)
        record_rollup_preview(timed.preview)
    increment_tick_runs("ok")
    preview = timed.preview if timed else None
    output = VolumeTickOutput(
        ticked_at=ticked_at.isoformat(),
        teams_with_logs=counts.total,
        minute_shard=minute_shard,
        teams_due_in_shard=counts.due_in_shard,
        due_bucket_start=due.start.isoformat(),
        due_bucket_end=due.end.isoformat(),
        rollup_rows=preview.rollup_rows if preview else None,
        source_rows=preview.source_rows if preview else None,
        distinct_services=preview.distinct_services if preview else None,
        rows_without_namespace=preview.rows_without_namespace if preview else None,
        rows_without_environment=preview.rows_without_environment if preview else None,
    )
    logger.info("logs_volume_tick_heartbeat", clickhouse_duration_ms=duration_ms, **dataclasses.asdict(output))
    return output
