from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import get_all_cohort_dependencies
from products.cohorts.backend.realtime_state import CohortRealtimeState, resolve_realtime_readiness
from products.cohorts.backend.realtime_teams import is_serving_team
from products.workflows.backend.facade.contracts import RealtimeCohortStatus


def find_behavioral_cohort_name(project_id: int, cohort_ids: list[int | str]) -> str | None:
    """The name of the first non-static cohort, among the given cohorts and their dependencies,
    that filters on event behavior. Static cohorts are exempt, because their membership is frozen."""
    for cohort_id in cohort_ids:
        try:
            cohort = Cohort.objects.get(pk=cohort_id, team__project_id=project_id, deleted=False)
        except (Cohort.DoesNotExist, ValueError, TypeError):
            continue  # missing/invalid cohort surfaces during audience resolution, not here
        if cohort.is_static:
            continue
        for dep in [cohort, *get_all_cohort_dependencies(cohort)]:
            if dep.is_static:
                continue
            if any(p.type == "behavioral" for p in dep.properties.flat):
                # Cohort.name is nullable, and the caller reads None as "no behavioral cohort".
                return str(dep.name)
    return None


def _filters_on_behavior(cohort: Cohort) -> bool:
    for dep in [cohort, *get_all_cohort_dependencies(cohort)]:
        if not dep.is_static and any(p.type == "behavioral" for p in dep.properties.flat):
            return True
    return False


# The filter kinds the realtime pipeline keys a cohort's membership on. A cohort with none of its own,
# such as one that only references other cohorts, never gets a membership or a readiness stamp.
_REALTIME_LEAF_TYPES = {"behavioral", "person", "person_metadata"}


def find_realtime_behavioral_cohort(project_id: int, cohort_ids: list[int | str]) -> Cohort | None:
    """The first realtime cohort among `cohort_ids` that filters on event behavior and that the realtime
    pipeline can calculate."""
    for cohort_id in cohort_ids:
        try:
            cohort = Cohort.objects.get(
                pk=cohort_id, team__project_id=project_id, deleted=False, cohort_type=CohortType.REALTIME
            )
        except (Cohort.DoesNotExist, ValueError, TypeError):
            continue
        has_own_leaf = any(p.type in _REALTIME_LEAF_TYPES for p in cohort.properties.flat)
        if has_own_leaf and _filters_on_behavior(cohort):
            return cohort
    return None


def sole_audience_cohort_id(filters: object) -> int | str | None:
    """The cohort ID of an audience of exactly one condition, "in" a cohort, or None. Reads no rows."""
    if not isinstance(filters, dict) or filters.get("filter_test_accounts"):
        return None
    properties = filters.get("properties")
    if not isinstance(properties, list) or len(properties) != 1:
        return None
    condition = properties[0]
    if (
        not isinstance(condition, dict)
        or condition.get("type") != "cohort"
        or condition.get("operator") not in (None, "in")
        or condition.get("negation")
    ):
        return None
    cohort_id = condition.get("value")
    return cohort_id if isinstance(cohort_id, int | str) else None


def realtime_audience_cohort(project_id: int, filters: object) -> Cohort | None:
    """The realtime cohort an audience sends to from the realtime pipeline's membership, or None.

    Only an audience of exactly one condition, "in" a realtime cohort that filters on event
    behavior, takes this path. The membership lives in a Postgres database that holds no person
    properties, so any other condition, a negated one, or the test account filter keeps the
    ClickHouse audience query.
    """
    cohort_id = sole_audience_cohort_id(filters)
    if cohort_id is None:
        return None
    return find_realtime_behavioral_cohort(project_id, [cohort_id])


def realtime_cohort_can_finish(cohort: Cohort) -> bool:
    """Whether this cohort's team is at the `serving` level, so the cohort can become ready at all.

    A `processing` team runs the pipeline, but its users must not see a realtime audience come alive.
    """
    return is_serving_team(cohort.team_id)


def realtime_cohort_is_ready(cohort: Cohort) -> bool:
    """Whether the realtime pipeline holds this cohort's full membership and keeps it current.

    The backfill stamps stay set when a team stops serving, but the pipeline may then stop updating
    the membership, so the team has to be serving too.
    """
    return cohort.is_flag_compatible and realtime_cohort_can_finish(cohort)


# The states the size response declares. Any other state of a cohort that isn't ready yet is building.
_REPORTED_PENDING_STATES = {CohortRealtimeState.REBUILDING, CohortRealtimeState.NEEDS_ATTENTION}


def realtime_cohort_status(cohort: Cohort) -> RealtimeCohortStatus:
    """Whether a realtime cohort audience can send now, and how far its calculation has come."""
    readiness = resolve_realtime_readiness([cohort]).get(cohort.pk)
    if realtime_cohort_is_ready(cohort):
        state: str = CohortRealtimeState.READY
    elif not is_serving_team(cohort.team_id):
        # The pipeline doesn't serve this team, so the cohort never finishes calculating.
        state = CohortRealtimeState.NEEDS_ATTENTION
    elif readiness is not None and readiness.state in _REPORTED_PENDING_STATES:
        state = readiness.state
    else:
        state = CohortRealtimeState.BUILDING
    build = readiness.build if readiness is not None else None
    return RealtimeCohortStatus(
        id=cohort.pk,
        name=str(cohort.name),
        state=state,
        percent_complete=build.percent_complete if build is not None and state != CohortRealtimeState.READY else None,
    )
