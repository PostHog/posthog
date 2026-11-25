"""Experiments reads for the cohorts product: the experiments whose queries filter on a cohort."""

import json

from django.db.models import Model, QuerySet

from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.facade.contracts import ExperimentsUsingCohort
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric

__all__ = ["experiments_using_cohort"]

# A cohort filter can hold the cohort id as a number or as a string.
_COHORT_FILTER_PATH = '$.** ? (@.type == "cohort" && (@.value == $id || @.value == $id_text))'

# An experiment's id, name, team and creator.
_Row = tuple[int, str, int, int | None]


def experiments_using_cohort(*, team: Team, user: User | None, cohort_id: int) -> ExperimentsUsingCohort:
    """The experiments of the project of `team` that are not archived or deleted and that filter on the cohort in their
    exposure criteria, their metrics or a linked shared metric. HogQL rejects a deleted cohort, so every query of such
    an experiment fails once the cohort is deleted.

    Names only the experiments that `user` may view, and none without `user`.
    """
    path_vars = json.dumps({"id": cohort_id, "id_text": str(cohort_id)})
    live = Experiment.objects.filter(team__project_id=team.project_id, deleted=False, archived=False)
    ids = set(
        _with_cohort_filter(live, ("exposure_criteria", "metrics", "metrics_secondary"), path_vars).values_list(
            "id", flat=True
        )
    )
    # Read first, because a subquery aliases the table that the condition names.
    shared_metric_ids = list(
        _with_cohort_filter(
            ExperimentSavedMetric.objects.filter(team__project_id=team.project_id), ("query",), path_vars
        ).values_list("id", flat=True)
    )
    if shared_metric_ids:
        ids.update(
            live.filter(experimenttosavedmetric__saved_metric_id__in=shared_metric_ids).values_list("id", flat=True)
        )
    if not ids:
        return ExperimentsUsingCohort(count=0, visible_names=())
    rows: list[_Row] = list(
        live.filter(id__in=ids).order_by("id").values_list("id", "name", "team_id", "created_by_id")
    )
    viewable = _viewable_ids(team, user, rows)
    return ExperimentsUsingCohort(
        count=len(rows),
        visible_names=tuple(name or "Unnamed" for experiment_id, name, _, _ in rows if experiment_id in viewable),
    )


def _with_cohort_filter[M: Model](queryset: QuerySet[M], fields: tuple[str, ...], path_vars: str) -> QuerySet[M]:
    # The table name comes from the model's metadata and the field names are constants of this module. The cohort id
    # goes in as a parameter.
    table = queryset.model._meta.db_table
    condition = " OR ".join(
        f"jsonb_path_exists({table}.{field}, '{_COHORT_FILTER_PATH}', %s::jsonb)" for field in fields
    )
    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
    return queryset.extra(where=[condition], params=[path_vars] * len(fields))


def _viewable_ids(team: Team, user: User | None, rows: list[_Row]) -> set[int]:
    if user is None:
        return set()
    # The access control reads the access rows of its own team only, so an experiment of another environment in the
    # project counts, but stays unnamed.
    own = [(experiment_id, created_by_id) for experiment_id, _, team_id, created_by_id in rows if team_id == team.id]
    denied = set(
        UserAccessControl(user=user, team=team, organization_id=str(team.organization_id)).denied_object_ids(
            "experiment",
            ((str(experiment_id), team.id, created_by_id) for experiment_id, created_by_id in own),
            "viewer",
        )
    )
    return {experiment_id for experiment_id, _ in own if str(experiment_id) not in denied}
