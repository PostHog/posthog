from uuid import UUID

from django.db.models import Count, Q

from temporalio import activity

from products.replay_vision.backend.enqueue_claims import pending_enqueue_claims
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import COUNT_IN_FLIGHT_APPLIES_TIMEOUT, in_flight_headroom
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
from products.replay_vision.backend.temporal.query_budget import bounded_queries
from products.replay_vision.backend.temporal.sweep_types import CountInFlightAppliesInputs, InFlightApplyCounts


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


def count_in_flight(
    team_id: int, scanner_id: UUID, backfill_id: UUID | None = None, rows: dict[str, int] | None = None
) -> dict[str, int]:
    """Capacity as the caps see it: persisted rows plus slots claimed but not yet persisted.

    Pass `rows` when the caller already has the raw counts, so the aggregate runs once rather than twice.
    """
    counts = dict(rows) if rows is not None else count_in_flight_rows(team_id, scanner_id, backfill_id)
    # The backfill claims matter as much as the others: without them the sub-cap only ever sees persisted
    # rows, so the next tick re-spends the slots this one took while its children were still queued.
    claims = pending_enqueue_claims(team_id, scanner_id, backfill_id)
    for scope, pending in claims.items():
        counts[scope] += pending
    return counts


@activity.defn
@track_activity()
def count_in_flight_by_team_activity(inputs: CountInFlightAppliesInputs) -> InFlightApplyCounts:
    with bounded_queries(COUNT_IN_FLIGHT_APPLIES_TIMEOUT):
        rows = count_in_flight_rows(inputs.team_id, inputs.scanner_id)
    counts = count_in_flight(inputs.team_id, inputs.scanner_id, rows=rows)
    team = counts["team"]
    scanner = counts["scanner"]
    # The workflow makes the same call on these counts; recorded here because metrics
    # can't be emitted from deterministic workflow code.
    if in_flight_headroom(scanner, team) <= 0:
        record_sweep_outcome("throttled")
    return InFlightApplyCounts(scanner=scanner, team=team)
