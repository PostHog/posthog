from products.cohorts.backend.models.cohort import Cohort
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
