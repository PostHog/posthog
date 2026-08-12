import time
import dataclasses
from datetime import UTC, datetime

import structlog
import temporalio.activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.sync import database_sync_to_async_pool

from products.logs.backend.temporal.volume_tick.constants import TEAMS_WITH_LOGS_WINDOW
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
    )
    return VolumeTickOutput(ticked_at=ticked_at.isoformat(), teams_with_logs=teams_with_logs)
