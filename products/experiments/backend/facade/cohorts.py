"""Experiments reads for the cohorts product: the experiments whose queries filter on a cohort."""

import json

from django.db.models import Model, QuerySet

from products.experiments.backend.facade.contracts import ExperimentCohortReference
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric

__all__ = ["experiments_using_cohort"]

# A cohort filter can hold the cohort id as a number or as a string.
_COHORT_FILTER_PATH = '$.** ? (@.type == "cohort" && (@.value == $id || @.value == $id_text))'


def experiments_using_cohort(*, project_id: int, cohort_id: int) -> tuple[ExperimentCohortReference, ...]:
    """The experiments of the project that are not archived or deleted and that filter on the cohort in their exposure
    criteria, their metrics or a linked shared metric, in id order. HogQL rejects a deleted cohort, so every query of
    such an experiment fails once the cohort is deleted."""
    path_vars = json.dumps({"id": cohort_id, "id_text": str(cohort_id)})
    live = Experiment.objects.filter(team__project_id=project_id, deleted=False, archived=False)
    ids = set(
        _with_cohort_filter(live, ("exposure_criteria", "metrics", "metrics_secondary"), path_vars).values_list(
            "id", flat=True
        )
    )
    # Read first, because a subquery aliases the table that the condition names.
    shared_metric_ids = list(
        _with_cohort_filter(
            ExperimentSavedMetric.objects.filter(team__project_id=project_id), ("query",), path_vars
        ).values_list("id", flat=True)
    )
    if shared_metric_ids:
        ids.update(
            live.filter(experimenttosavedmetric__saved_metric_id__in=shared_metric_ids).values_list("id", flat=True)
        )
    if not ids:
        return ()
    return tuple(
        ExperimentCohortReference(id=experiment_id, name=name, team_id=team_id, created_by_id=created_by_id)
        for experiment_id, name, team_id, created_by_id in live.filter(id__in=ids)
        .order_by("id")
        .values_list("id", "name", "team_id", "created_by_id")
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
