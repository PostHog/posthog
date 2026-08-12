import time
import dataclasses
from datetime import UTC, datetime, timedelta

import structlog
import temporalio.activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

from products.logs.backend.temporal.volume_tick.constants import (
    BUCKET_MINUTES,
    BUCKET_SECONDS,
    FINALIZATION_ALLOWANCE,
    TEAMS_WITH_LOGS_WINDOW,
)
from products.logs.backend.temporal.volume_tick.metrics import (
    increment_tick_runs,
    record_clickhouse_duration,
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


@temporalio.activity.defn
async def volume_tick_heartbeat_activity(input: VolumeTickInput) -> VolumeTickOutput:
    # Skeleton for the log volume rollup tick: proves the schedule and the
    # worker's path to the logs ClickHouse cluster, and observes (never writes)
    # what the real tick would do. The rollup writer replaces this body.
    ticked_at = datetime.now(UTC)
    due = due_bucket_bounds(ticked_at)
    # One team cohort per minute of the bucket: the every-minute schedule smears
    # teams across the bucket's minutes, so team_id % BUCKET_MINUTES is the shard.
    # Observed, not enforced: no per-shard work happens yet.
    minute_shard = ticked_at.minute % BUCKET_MINUTES
    started = time.monotonic()
    try:
        counts = await _count_teams_with_logs_async(ticked_at - TEAMS_WITH_LOGS_WINDOW, ticked_at, minute_shard)
    except Exception:
        increment_tick_runs("error")
        raise
    duration_ms = int((time.monotonic() - started) * 1000)

    record_clickhouse_duration(duration_ms)
    record_teams_with_logs(counts.total)
    increment_tick_runs("ok")
    output = VolumeTickOutput(
        ticked_at=ticked_at.isoformat(),
        teams_with_logs=counts.total,
        minute_shard=minute_shard,
        teams_due_in_shard=counts.due_in_shard,
        due_bucket_start=due.start.isoformat(),
        due_bucket_end=due.end.isoformat(),
    )
    logger.info("logs_volume_tick_heartbeat", clickhouse_duration_ms=duration_ms, **dataclasses.asdict(output))
    return output
