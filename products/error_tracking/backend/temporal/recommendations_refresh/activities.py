import structlog
from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload

from products.error_tracking.backend.logic.recommendations.refresh import refresh_teams_recommendations_batched
from products.error_tracking.backend.temporal.recommendations_refresh.types import (
    RecommendationsRefreshInputs,
    RefreshBatchInputs,
    RefreshBatchResult,
)

logger = structlog.get_logger(__name__)

# Teams that ingested at least one exception in the lookback window, heaviest first.
# Runs on the offline cluster so the cross-team scan doesn't compete with user queries.
TEAMS_WITH_RECENT_EXCEPTIONS_QUERY = """
    SELECT team_id, count() AS exception_count
    FROM events
    WHERE event = '$exception'
      AND timestamp > now() - toIntervalDay(%(lookback_days)s)
    GROUP BY team_id
    ORDER BY exception_count DESC
"""


def pack_team_batches(teams_with_counts: list[tuple[int, int]], max_teams: int, max_events: int) -> list[list[int]]:
    """Greedily pack (team_id, event_count) pairs, heaviest first, closing a batch when
    it reaches ``max_teams`` or adding the next team would push it past ``max_events``.
    A single team above the volume cap gets a batch of its own."""
    batches: list[list[int]] = []
    current: list[int] = []
    current_events = 0
    for team_id, count in teams_with_counts:
        if current and (len(current) >= max_teams or current_events + count > max_events):
            batches.append(current)
            current = []
            current_events = 0
        current.append(team_id)
        current_events += count
    if current:
        batches.append(current)
    return batches


@activity.defn
def get_team_batches_activity(inputs: RecommendationsRefreshInputs) -> list[list[int]]:
    rows = sync_execute(
        TEAMS_WITH_RECENT_EXCEPTIONS_QUERY,
        {"lookback_days": inputs.lookback_days},
        workload=Workload.OFFLINE,
    )
    batches = pack_team_batches(
        [(int(team_id), int(count)) for team_id, count in rows],
        max_teams=inputs.batch_size,
        max_events=inputs.max_events_per_batch,
    )
    logger.info(
        "error_tracking.recommendations_refresh.teams_enumerated",
        team_count=len(rows),
        batch_count=len(batches),
        lookback_days=inputs.lookback_days,
    )
    return batches


@activity.defn
def refresh_recommendations_batch_activity(inputs: RefreshBatchInputs) -> RefreshBatchResult:
    teams_processed, kicked = refresh_teams_recommendations_batched(inputs.team_ids, on_progress=activity.heartbeat)
    return RefreshBatchResult(teams_processed=teams_processed, recommendations_kicked=kicked)
