from uuid import UUID

from django.db.models import Count, Q

import structlog
from temporalio import activity

from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.enqueue_claims import (
    pending_enqueue_claims_for_scanner,
    pending_enqueue_claims_for_team,
)
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import in_flight_headroom
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
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


def count_in_flight_rows(team_id: int, scanner_id: UUID, backfill_id: UUID | None = None) -> dict[str, int]:
    """Persisted pending/running rows for a scanner, its whole team, and optionally one backfill.

    Rows rather than Temporal visibility, so concurrency shares the quota system's single notion of
    in-flight. Callers enforcing a cap want `count_in_flight` below; this raw form is for the claim
    protocol, which adds outstanding claims itself.
    """
    aggregates = {
        "team": Count("id"),
        "scanner": Count("id", filter=Q(scanner_id=scanner_id)),
    }
    if backfill_id is not None:
        aggregates["backfill"] = Count("id", filter=Q(backfill_id=backfill_id))
    return ReplayObservation.in_flight_for_team(team_id).aggregate(**aggregates)


def count_in_flight(team_id: int, scanner_id: UUID, backfill_id: UUID | None = None) -> dict[str, int]:
    """Capacity as the caps see it: persisted rows plus slots claimed but not yet persisted."""
    counts = count_in_flight_rows(team_id, scanner_id, backfill_id)
    counts["team"] += pending_enqueue_claims_for_team(team_id)
    counts["scanner"] += pending_enqueue_claims_for_scanner(scanner_id)
    return counts


@activity.defn
@track_activity()
def count_in_flight_by_team_activity(inputs: CountInFlightAppliesInputs) -> InFlightApplyCounts:
    counts = count_in_flight(inputs.team_id, inputs.scanner_id)
    team = counts["team"]
    scanner = counts["scanner"]
    # The workflow makes the same call on these counts; recorded here because metrics
    # can't be emitted from deterministic workflow code.
    if in_flight_headroom(scanner, team) <= 0:
        record_sweep_outcome("throttled")
    return InFlightApplyCounts(scanner=scanner, team=team)
