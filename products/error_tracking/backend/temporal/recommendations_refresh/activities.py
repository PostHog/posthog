from django.db import close_old_connections

import structlog
from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload

from products.error_tracking.backend.recommendations.refresh import refresh_team_recommendations
from products.error_tracking.backend.temporal.recommendations_refresh.types import (
    RecommendationsRefreshInputs,
    RefreshBatchInputs,
    RefreshBatchResult,
)

logger = structlog.get_logger(__name__)

# Distinct teams that ingested at least one exception in the lookback window.
# Runs on the offline cluster so the cross-team scan doesn't compete with user queries.
TEAMS_WITH_RECENT_EXCEPTIONS_QUERY = """
    SELECT DISTINCT team_id
    FROM events
    WHERE event = '$exception'
      AND timestamp > now() - toIntervalDay(%(lookback_days)s)
"""


@activity.defn
def get_teams_with_recent_exceptions_activity(inputs: RecommendationsRefreshInputs) -> list[int]:
    rows = sync_execute(
        TEAMS_WITH_RECENT_EXCEPTIONS_QUERY,
        {"lookback_days": inputs.lookback_days},
        workload=Workload.OFFLINE,
    )
    team_ids = [int(row[0]) for row in rows]
    logger.info(
        "error_tracking.recommendations_refresh.teams_enumerated",
        team_count=len(team_ids),
        lookback_days=inputs.lookback_days,
    )
    return team_ids


@activity.defn
def refresh_recommendations_batch_activity(inputs: RefreshBatchInputs) -> RefreshBatchResult:
    close_old_connections()
    kicked = 0
    for index, team_id in enumerate(inputs.team_ids):
        # refresh_team_recommendations swallows per-team errors, so one bad team
        # never sinks the batch.
        kicked += refresh_team_recommendations(team_id, compute_sync=True)
        activity.heartbeat(index)
    return RefreshBatchResult(teams_processed=len(inputs.team_ids), recommendations_kicked=kicked)
