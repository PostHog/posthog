from typing import Literal

from django.db.models import Q, QuerySet

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.experiments.backend.facade.contracts import ListAccess
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric


def visible_to[ModelT: (Experiment, ExperimentSavedMetric)](
    queryset: QuerySet[ModelT], access: ListAccess | None
) -> QuerySet[ModelT]:
    # The same narrowing `UserAccessControl.filter_queryset_by_access_level` applies to a queryset list.
    if access is None:
        return queryset
    # `created_by_id=None` would match every record without a creator, so a viewer without an id owns nothing.
    own = Q(created_by_id=access.viewer_id) if access.viewer_id is not None else Q(pk__in=[])
    if access.only_allowed:
        return queryset.filter(Q(id__in=access.allowed_ids) | own)
    if access.blocked_ids:
        return queryset.exclude(Q(id__in=access.blocked_ids) & ~own)
    return queryset


def visible_experiments(team_id: int, access: ListAccess | None) -> QuerySet[Experiment]:
    """The team's experiments that `access` lets the viewer see. None means no narrowing."""
    return visible_to(Experiment.objects.filter(team_id=team_id), access)


def visible_saved_metrics(team_id: int, access: ListAccess | None) -> QuerySet[ExperimentSavedMetric]:
    """The team's shared metrics that `access` lets the viewer see. None means no narrowing."""
    return visible_to(ExperimentSavedMetric.objects.filter(team_id=team_id), access)


def list_access(
    resource: Literal["experiment", "experiment_saved_metric"],
    *,
    team_id: int,
    subject: Subject | None,
    include_all_if_admin: bool = False,
) -> ListAccess | None:
    """The narrowing that the SDK's QuerySet filter applies to a list of `resource`, for a facade that pages the list.

    `team_id` is the team whose rules apply. None means no narrowing.
    """
    result = authorization.list_objects(
        resource=Resource(type=ResourceType(resource), project_id=team_id),
        action=Action.QUERY if include_all_if_admin else Action.VIEW,
        subject=subject,
        creator_exempt=True,
    )
    if not result.complete:
        # The SDK caps a list only when the caller passes a limit. The current rules never cap one and always keep
        # the creator's records, so a capped answer keeps only the viewer's own records.
        return ListAccess(
            viewer_id=authorization.principal_user_id(subject=subject),
            only_allowed=True,
            allowed_ids=frozenset(),
            blocked_ids=frozenset(),
        )
    if result.excluded and not result.ids:
        return None
    viewer_id = result.creator_user_id if result.creator_exempt else None
    if result.excluded:
        return ListAccess(viewer_id=viewer_id, only_allowed=False, allowed_ids=frozenset(), blocked_ids=result.ids)
    return ListAccess(viewer_id=viewer_id, only_allowed=True, allowed_ids=result.ids, blocked_ids=frozenset())
