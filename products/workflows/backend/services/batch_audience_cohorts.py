from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import get_all_cohort_dependencies


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


def find_realtime_behavioral_cohort(project_id: int, cohort_ids: list[int | str]) -> Cohort | None:
    """The first realtime cohort among `cohort_ids` that filters on event behavior."""
    for cohort_id in cohort_ids:
        try:
            cohort = Cohort.objects.get(
                pk=cohort_id, team__project_id=project_id, deleted=False, cohort_type=CohortType.REALTIME
            )
        except (Cohort.DoesNotExist, ValueError, TypeError):
            continue
        if _filters_on_behavior(cohort):
            return cohort
    return None


def realtime_audience_cohort(project_id: int, filters: object) -> Cohort | None:
    """The realtime cohort an audience sends to from the realtime pipeline's membership, or None.

    Only an audience of exactly one condition, "in" a realtime cohort that filters on event
    behavior, takes this path. The membership lives in a Postgres database that holds no person
    properties, so any other condition, a negated one, or the test account filter keeps the
    ClickHouse audience query.
    """
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
    return find_realtime_behavioral_cohort(project_id, [condition.get("value")])
