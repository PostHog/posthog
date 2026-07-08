from django.db.models import Count, Q

from temporalio import activity

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.sweep_types import CountInFlightAppliesInputs, InFlightApplyCounts


@activity.defn
@track_activity()
def count_in_flight_applies_activity(inputs: CountInFlightAppliesInputs) -> InFlightApplyCounts:
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
