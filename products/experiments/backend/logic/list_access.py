from django.db.models import Q, QuerySet

from products.experiments.backend.facade.contracts import ListAccess
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric


def visible_to[ModelT: (Experiment, ExperimentSavedMetric)](
    queryset: QuerySet[ModelT], access: ListAccess | None
) -> QuerySet[ModelT]:
    # The same narrowing `UserAccessControl.filter_queryset_by_access_level` applies to a queryset list.
    if access is None:
        return queryset
    if access.only_allowed:
        return queryset.filter(Q(id__in=access.allowed_ids) | Q(created_by_id=access.viewer_id))
    if access.blocked_ids:
        return queryset.exclude(Q(id__in=access.blocked_ids) & ~Q(created_by_id=access.viewer_id))
    return queryset


def visible_experiments(team_id: int, access: ListAccess | None) -> QuerySet[Experiment]:
    """The team's experiments that `access` lets the viewer see. None means no narrowing."""
    return visible_to(Experiment.objects.filter(team_id=team_id), access)


def visible_saved_metrics(team_id: int, access: ListAccess | None) -> QuerySet[ExperimentSavedMetric]:
    """The team's shared metrics that `access` lets the viewer see. None means no narrowing."""
    return visible_to(ExperimentSavedMetric.objects.filter(team_id=team_id), access)
