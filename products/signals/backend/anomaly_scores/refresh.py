"""The scheduled refresh of the anomaly scoring due list: a Temporal workflow apart from the tick.

The `due_list` field of the `anomaly-scoring` flag payload gates the work. See `due_list.py`.
"""

import time
import datetime

from django.conf import settings
from django.utils import timezone

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.ph_client import ph_background_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.anomaly_scores.config import ANOMALY_SCORING_FLAG_DISTINCT_ID, read_config, read_payload
from products.signals.backend.anomaly_scores.due_list import refresh_due_list
from products.signals.backend.anomaly_scores.tick import capture_census

REFRESH_WORKFLOW_NAME = "anomaly-scoring-due-list-refresh"
# No team starts to refresh after this time. The teams that are left go first on the next run.
_REFRESH_BUDGET = datetime.timedelta(minutes=5)
# One team can still run after the budget, and its census and summary captures run after it.
_REFRESH_ACTIVITY_TIMEOUT = datetime.timedelta(minutes=10)
REFRESH_TIMEOUT = _REFRESH_ACTIVITY_TIMEOUT * 2


@frozen
class DueListRefreshInput:
    pass


@frozen
class DueListRefreshResult:
    enabled: bool = False
    teams_refreshed: int = 0
    teams_failed: int = 0
    teams_waiting: int = 0
    rows_added: int = 0
    rows_removed: int = 0
    duration_ms: int = 0


def run_refresh(now: datetime.datetime) -> DueListRefreshResult:
    started = time.monotonic()
    config = read_config(read_payload())
    refresh = refresh_due_list(config, now, deadline=started + _REFRESH_BUDGET.total_seconds())
    if not refresh.enabled:
        return DueListRefreshResult()
    capture_census(refresh.census or [], now)
    result = DueListRefreshResult(
        enabled=True,
        teams_refreshed=refresh.teams_refreshed,
        teams_failed=refresh.teams_failed,
        teams_waiting=refresh.teams_waiting,
        rows_added=refresh.rows_added,
        rows_removed=refresh.rows_removed,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    ph_background_capture()(
        distinct_id=ANOMALY_SCORING_FLAG_DISTINCT_ID,
        event="anomaly scoring due list refresh",
        properties={
            "deployment": settings.CLOUD_DEPLOYMENT,
            "teams_refreshed": result.teams_refreshed,
            "teams_failed": result.teams_failed,
            "teams_waiting": result.teams_waiting,
            "rows_added": result.rows_added,
            "rows_removed": result.rows_removed,
            "duration_ms": result.duration_ms,
            "active_insights": refresh.active,
            **{f"active_{reason}": count for reason, count in (refresh.active_reasons or {}).items()},
        },
    )
    return result


@activity.defn
@scoped_temporal()
@close_db_connections
async def refresh_anomaly_scoring_due_list_activity(input: DueListRefreshInput) -> DueListRefreshResult:
    return await database_sync_to_async(run_refresh, thread_sensitive=False)(timezone.now())


@workflow.defn(name=REFRESH_WORKFLOW_NAME)
class AnomalyScoringDueListRefreshWorkflow:
    @workflow.run
    async def run(self, inputs: DueListRefreshInput) -> DueListRefreshResult:
        return await workflow.execute_activity(
            refresh_anomaly_scoring_due_list_activity,
            inputs,
            start_to_close_timeout=_REFRESH_ACTIVITY_TIMEOUT,
            # A failed run leaves its teams waiting, and the next run starts with them.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
