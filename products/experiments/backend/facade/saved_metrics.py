"""Shared metrics capability: the reads and writes of the shared metrics API.

A write that the API must refuse raises the `ValidationError` of Django REST framework, with the message the
API returns.
"""

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.paging import Page, PageRequest

from products.experiments.backend.experiment_creator import to_experiment_creator
from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService
from products.experiments.backend.logic import saved_metrics
from products.experiments.backend.metric_utils import refresh_action_names_in_metric
from products.experiments.backend.models.experiment import ExperimentSavedMetric

from .contracts import (
    LinkedExperiment,
    ListAccess,
    SavedMetric,
    SavedMetricListFilters,
    SavedMetricNotFound,
    SavedMetricWrite,
)


def _to_saved_metric(metric: ExperimentSavedMetric, team: Team) -> SavedMetric:
    return SavedMetric(
        id=metric.id,
        team_id=metric.team_id,
        name=metric.name,
        description=metric.description,
        query=refresh_action_names_in_metric(metric.query, team) or metric.query,
        created_by_id=metric.created_by_id,
        created_by=to_experiment_creator(metric.created_by) if metric.created_by else None,
        created_at=metric.created_at,
        updated_at=metric.updated_at,
        tags=tuple(tagged_item.tag.name for tagged_item in getattr(metric, "prefetched_tags", ())),
    )


def list_saved_metrics(
    *, team: Team, filters: SavedMetricListFilters, access: ListAccess | None, page: PageRequest
) -> Page[SavedMetric]:
    """One page of the team's shared metrics that pass the filters and `access`, in name order."""
    return saved_metrics.list_page(team=team, filters=filters, access=access, page=page).map(
        lambda metric: _to_saved_metric(metric, team)
    )


def get_saved_metric(*, team: Team, saved_metric_id: int) -> SavedMetric | None:
    """The team's shared metric with the id, or None when the team has no such metric."""
    metric = saved_metrics.get(team_id=team.id, saved_metric_id=saved_metric_id)
    return None if metric is None else _to_saved_metric(metric, team)


def find_saved_metric_id_by_name(*, team_id: int, name: str, exclude_saved_metric_id: int | None = None) -> int | None:
    """The id of a shared metric of the team with this name in any case, other than `exclude_saved_metric_id`."""
    return saved_metrics.colliding_id(team_id=team_id, name=name, exclude_saved_metric_id=exclude_saved_metric_id)


def list_linked_experiments(*, team_id: int, saved_metric_id: int, access: ListAccess | None) -> list[LinkedExperiment]:
    """The experiments that use the shared metric and are not deleted, newest first, narrowed by `access`."""
    return [
        LinkedExperiment(id=experiment.id, name=experiment.name, is_running=experiment.is_running)
        for experiment in saved_metrics.linked_experiments(
            team_id=team_id, saved_metric_id=saved_metric_id, access=access
        )
    ]


def create_saved_metric(*, team: Team, user: User, write: SavedMetricWrite) -> SavedMetric:
    """Create a shared metric in the team. The query is validated and gets a new uuid."""
    if write.name is None or write.query is None:
        raise ValueError("A new shared metric needs a name and a query.")
    metric = ExperimentSavedMetricService(team=team, user=user).create_saved_metric(
        name=write.name, query=write.query, description=write.description
    )
    if "tags" in write.fields_set:
        saved_metrics.set_tags(metric, write.tags)
    return _to_saved_metric(metric, team)


def update_saved_metric(*, team: Team, user: User, saved_metric_id: int, write: SavedMetricWrite) -> SavedMetric:
    """Change the fields of the shared metric that the write names. A changed query is validated again."""
    metric = saved_metrics.get(team_id=team.id, saved_metric_id=saved_metric_id)
    if metric is None:
        raise SavedMetricNotFound(saved_metric_id)
    changes = {field: getattr(write, field) for field in write.fields_set if field != "tags"}
    metric = ExperimentSavedMetricService(team=team, user=user).update_saved_metric(metric, changes)
    if "tags" in write.fields_set:
        saved_metrics.set_tags(metric, write.tags)
    return _to_saved_metric(metric, team)


def delete_saved_metric(*, team: Team, user: User, saved_metric_id: int) -> None:
    metric = saved_metrics.get(team_id=team.id, saved_metric_id=saved_metric_id)
    if metric is None:
        raise SavedMetricNotFound(saved_metric_id)
    ExperimentSavedMetricService(team=team, user=user).delete_saved_metric(metric)
