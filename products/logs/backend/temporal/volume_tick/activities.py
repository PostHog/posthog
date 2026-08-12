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


@dataclasses.dataclass(frozen=True)
class VolumeTickInput:
    pass


@dataclasses.dataclass(frozen=True)
class VolumeTickOutput:
    ticked_at: str
    teams_with_logs: int
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


def count_teams_with_logs(begin: datetime, end: datetime) -> int:
    """Distinct teams with at least one log record in [begin, end).

    Queries the physical `logs_distributed` table, not `logs` — `logs` is the
    HogQL table alias and does not exist for raw `sync_execute` SQL.
    """
    with tags_context(product=Product.LOGS, feature=Feature.PREAGGREGATION):
        rows = sync_execute(
            """
            SELECT count(DISTINCT team_id)
            FROM logs_distributed
            WHERE timestamp >= %(begin)s AND timestamp < %(end)s
            """,
            {"begin": begin, "end": end},
            workload=Workload.LOGS,
        )
    return int(rows[0][0])


@temporalio.activity.defn
async def volume_tick_heartbeat_activity(input: VolumeTickInput) -> VolumeTickOutput:
    # Scheduling skeleton for the log volume rollup: proves the every-minute
    # schedule and the worker's path to the logs ClickHouse cluster end to end.
    # No aggregation runs yet; the rollup writer replaces this body.
    ticked_at = datetime.now(UTC)
    due = due_bucket_bounds(ticked_at)
    started = time.monotonic()
    try:
        teams_with_logs = await database_sync_to_async_pool(count_teams_with_logs)(
            ticked_at - TEAMS_WITH_LOGS_WINDOW, ticked_at
        )
    except Exception:
        increment_tick_runs("error")
        raise
    duration_ms = int((time.monotonic() - started) * 1000)

    record_clickhouse_duration(duration_ms)
    record_teams_with_logs(teams_with_logs)
    increment_tick_runs("ok")
    logger.info(
        "logs_volume_tick_heartbeat",
        ticked_at=ticked_at.isoformat(),
        teams_with_logs=teams_with_logs,
        clickhouse_duration_ms=duration_ms,
        due_bucket_start=due.start.isoformat(),
        due_bucket_end=due.end.isoformat(),
    )
    return VolumeTickOutput(
        ticked_at=ticked_at.isoformat(),
        teams_with_logs=teams_with_logs,
        due_bucket_start=due.start.isoformat(),
        due_bucket_end=due.end.isoformat(),
    )
