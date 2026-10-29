"""Save-time checks on a workflow's steps that need the database or shared parsing rules."""

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import RealtimeAudienceCohort
from products.workflows.backend.services import batch_audience_cohorts
from products.workflows.backend.services.batch_audience_cohorts import find_behavioral_cohort_name
from products.workflows.backend.services.wait_clock_conditions import find_clock_function
from products.workflows.backend.utils.durations import (
    DURATION_PATTERN,
    duration_cap_error,
    duration_error,
    duration_minutes,
    exceeds_unit_cap,
    is_duration,
    is_signed_duration,
)


def _to_realtime_audience_cohort(cohort: Cohort | None) -> RealtimeAudienceCohort | None:
    if cohort is None:
        return None
    return RealtimeAudienceCohort(
        id=cohort.pk,
        name=str(cohort.name),
        ready=batch_audience_cohorts.realtime_cohort_is_ready(cohort),
        can_finish=batch_audience_cohorts.realtime_cohort_can_finish(cohort),
    )


def realtime_cohort_cant_finish_error(cohort: RealtimeAudienceCohort) -> str:
    return (
        f"Cohort '{cohort.name}' can't be calculated in real time for this project, so a send to it would never "
        "start. Use another cohort."
    )


def find_realtime_behavioral_cohort(project_id: int, cohort_ids: list[int | str]) -> RealtimeAudienceCohort | None:
    """The first realtime cohort among `cohort_ids` that filters on event behavior."""
    return _to_realtime_audience_cohort(batch_audience_cohorts.find_realtime_behavioral_cohort(project_id, cohort_ids))


def realtime_audience_cohort(project_id: int, filters: object) -> RealtimeAudienceCohort | None:
    """The realtime cohort an audience sends to from the realtime pipeline's membership, or None."""
    return _to_realtime_audience_cohort(batch_audience_cohorts.realtime_audience_cohort(project_id, filters))


__all__ = [
    "DURATION_PATTERN",
    "duration_cap_error",
    "duration_error",
    "duration_minutes",
    "exceeds_unit_cap",
    "find_behavioral_cohort_name",
    "find_clock_function",
    "find_realtime_behavioral_cohort",
    "is_duration",
    "is_signed_duration",
    "realtime_audience_cohort",
    "realtime_cohort_cant_finish_error",
]
