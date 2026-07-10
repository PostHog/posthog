from django.db.models import Count, Q

import structlog
from temporalio import activity

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.sweep_types import CountInFlightAppliesInputs, InFlightApplyCounts

logger = structlog.get_logger(__name__)


@activity.defn
@track_activity()
async def count_in_flight_applies_activity(inputs: CountInFlightAppliesInputs) -> int:
    """Legacy visibility-based scanner counter, retained so pre-deploy sweeps can replay their recorded
    int result; the wf.patched branch in the workflow routes new executions to the team-aware activity below.

    Fails open (returns 0) so a visibility hiccup lets the sweep proceed rather than wedging it.
    """
    query = f'PostHogScannerId = "{inputs.scanner_id}" AND ExecutionStatus = "Running"'
    try:
        client = await async_connect()
        return (await client.count_workflows(query)).count
    except Exception as exc:
        logger.warning("replay_vision.count_in_flight_failed", scanner_id=str(inputs.scanner_id), error=str(exc))
        return 0


@activity.defn
@close_db_connections
@track_activity()
def count_in_flight_by_team_activity(inputs: CountInFlightAppliesInputs) -> InFlightApplyCounts:
    """Count in-flight (pending/running) observations for this scanner and for its whole team.

    Counts DB rows rather than Temporal visibility so concurrency shares the quota system's
    single notion of in-flight. Rows stranded by failed workflows keep counting until the orphan
    reaper clears them, which throttles sweeps during an incident instead of piling on new work.
    """
    counts = ReplayObservation.in_flight_for_team(inputs.team_id).aggregate(
        team=Count("id"),
        scanner=Count("id", filter=Q(scanner_id=inputs.scanner_id)),
    )
    return InFlightApplyCounts(scanner=counts["scanner"], team=counts["team"])
