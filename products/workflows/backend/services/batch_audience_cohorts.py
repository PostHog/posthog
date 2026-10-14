from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.models.team.team import Team

from products.cdp.backend.filters import collect_property_cohort_ids
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import get_all_cohort_dependencies

# The current members of one realtime cohort. The cohort id comes from a Cohort row, never from
# the request, and is formatted as an int.
_REALTIME_MEMBERS_SUBQUERY = (
    "(SELECT person_id FROM posthog.realtime_cohort_membership WHERE cohort_id = {cohort_id} "
    "GROUP BY person_id HAVING argMax(status, last_updated) = 'entered')"
)


def _filters_on_behavior(cohort: Cohort) -> bool:
    for dep in [cohort, *get_all_cohort_dependencies(cohort)]:
        if not dep.is_static and any(p.type == "behavioral" for p in dep.properties.flat):
            return True
    return False


def find_behavioral_cohort_name(
    project_id: int, cohort_ids: list[int | str], exempt_cohort_ids: frozenset[int] = frozenset()
) -> str | None:
    """The name of the first non-static cohort, among the given cohorts and their dependencies,
    that filters on event behavior. Static cohorts are exempt, because their membership is frozen.
    So are `exempt_cohort_ids`, which the audience reads from realtime membership instead."""
    for cohort_id in cohort_ids:
        try:
            cohort = Cohort.objects.get(pk=cohort_id, team__project_id=project_id, deleted=False)
        except (Cohort.DoesNotExist, ValueError, TypeError):
            continue  # missing/invalid cohort surfaces during audience resolution, not here
        if cohort.is_static or cohort.pk in exempt_cohort_ids:
            continue
        for dep in [cohort, *get_all_cohort_dependencies(cohort)]:
            if dep.is_static:
                continue
            if any(p.type == "behavioral" for p in dep.properties.flat):
                # Cohort.name is nullable, and the caller reads None as "no behavioral cohort".
                return str(dep.name)
    return None


def split_realtime_audience_cohorts(project_id: int, cohort_ids: set[int]) -> tuple[set[int], Cohort | None]:
    """The behavioral realtime cohorts among `cohort_ids` that are ready to read from realtime
    membership, and the first one that is not ready.

    Only behavioral realtime cohorts read realtime membership. A realtime cohort on person
    properties alone keeps the inline evaluation it had before realtime membership existed.
    """
    ready: set[int] = set()
    unready: Cohort | None = None
    # nosemgrep: idor-lookup-without-team (scoped by team__project_id)
    for cohort in Cohort.objects.filter(
        pk__in=cohort_ids, team__project_id=project_id, deleted=False, cohort_type=CohortType.REALTIME
    ).order_by("pk"):
        if not _filters_on_behavior(cohort):
            continue
        if cohort.is_flag_compatible:
            ready.add(cohort.pk)
        elif unready is None:
            unready = cohort
    return ready, unready


def lower_realtime_cohorts(team: Team, filters: dict) -> dict:
    """Rewrite each behavioral realtime cohort in an audience to read realtime membership.

    The default `IN COHORT` lowering reads precalculated membership, which the realtime pipeline
    does not maintain. The rewrite happens at query time, so the stored trigger keeps plain
    cohort references.

    Raises when a cohort lost its realtime readiness after the audience was saved: an answer
    from the wrong membership would send to the wrong people.
    """
    properties = filters.get("properties") if isinstance(filters, dict) else None
    if not properties:
        return filters

    cohort_ids = collect_property_cohort_ids(properties)
    if not cohort_ids:
        return filters

    ready, unready = split_realtime_audience_cohorts(team.project_id, cohort_ids)
    if unready is not None:
        raise ValidationError(
            {
                "filters": (
                    f"Cohort '{unready.name}' isn't ready for realtime evaluation. "
                    "Wait until it finishes calculating, then try again."
                )
            }
        )
    if not ready:
        return filters

    def lower(node: Any) -> Any:
        if isinstance(node, list):
            return [lower(item) for item in node]
        if not isinstance(node, dict):
            return node
        if node.get("type") in ("AND", "OR"):
            return {**node, "values": lower(node.get("values") or [])}
        if node.get("type") == "cohort":
            value = node.get("value")
            cohort_id = int(value) if isinstance(value, int | str) and str(value).isdigit() else None
            if cohort_id in ready:
                operator = "NOT IN" if node.get("operator") == "not_in" else "IN"
                return {
                    "type": "hogql",
                    "key": f"persons.id {operator} {_REALTIME_MEMBERS_SUBQUERY.format(cohort_id=cohort_id)}",
                }
        return node

    return {**filters, "properties": lower(properties)}
