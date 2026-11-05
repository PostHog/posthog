"""Test-support facade for experiments.

Test suites outside this product plant experiments, holdouts, saved metrics and the team
experiments config through here instead of importing the models. Ids go in and ids come out.

The helpers write rows directly. `facade.api.create_experiment` is the production door, but it
creates the feature flag from a key and validates the metrics, and the outside suites bring a
flag they made themselves.
"""

from datetime import datetime
from typing import Any

from asgiref.sync import sync_to_async

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


def create_experiment(
    *,
    team_id: int,
    feature_flag_id: int,
    name: str = "Test experiment",
    description: str | None = None,
    created_by_id: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    holdout_id: int | None = None,
    parameters: dict[str, Any] | None = None,
    filters: dict[str, Any] | None = None,
    metrics: list[dict[str, Any]] | None = None,
    metrics_secondary: list[dict[str, Any]] | None = None,
    exposure_criteria: dict[str, Any] | None = None,
    excluded_variants: list[str] | None = None,
    archived: bool = False,
    deleted: bool = False,
    updated_at: datetime | None = None,
) -> int:
    """Create an experiment on an existing feature flag, and return its id.

    The save derives the status from the dates: no `start_date` is a draft, a `start_date` is
    running, and both dates are stopped. JSON fields left as None take the model defaults.
    """
    json_fields = {
        "parameters": parameters,
        "filters": filters,
        "metrics": metrics,
        "metrics_secondary": metrics_secondary,
        "exposure_criteria": exposure_criteria,
    }
    experiment = Experiment.objects.create(
        team_id=team_id,
        feature_flag_id=feature_flag_id,
        name=name,
        description=description,
        created_by_id=created_by_id,
        start_date=start_date,
        end_date=end_date,
        holdout_id=holdout_id,
        excluded_variants=excluded_variants,
        archived=archived,
        deleted=deleted,
        **{field: value for field, value in json_fields.items() if value is not None},
    )
    if updated_at is not None:
        # updated_at is auto_now, so the insert overwrites it and only an update can backdate it.
        Experiment.objects.filter(team_id=team_id, id=experiment.id).update(updated_at=updated_at)
    return experiment.id


acreate_experiment = sync_to_async(create_experiment)


def update_experiment(*, team_id: int, experiment_id: int, **fields: Any) -> None:
    """Set fields on an experiment and save it, so the save signals fire as they do for a production
    write. `deleted=True` is a soft delete."""
    experiment = Experiment.objects.get(team_id=team_id, id=experiment_id)
    for field, value in fields.items():
        # setattr accepts any name, so a misspelled field would save nothing and pass silently.
        Experiment._meta.get_field(field)
        setattr(experiment, field, value)
    experiment.save()


def delete_experiment(*, team_id: int, experiment_id: int) -> None:
    """Remove the experiment row, which fires the delete signals."""
    Experiment.objects.get(team_id=team_id, id=experiment_id).delete()


def create_holdout(
    *,
    team_id: int,
    name: str,
    filters: list[dict[str, Any]] | None = None,
    created_by_id: int | None = None,
) -> int:
    holdout = ExperimentHoldout.objects.create(
        team_id=team_id,
        name=name,
        created_by_id=created_by_id,
        **({} if filters is None else {"filters": filters}),
    )
    return holdout.id


def create_saved_metric(
    *,
    team_id: int,
    name: str,
    query: dict[str, Any],
    description: str | None = None,
    created_by_id: int | None = None,
) -> int:
    saved_metric = ExperimentSavedMetric.objects.create(
        team_id=team_id, name=name, description=description, query=query, created_by_id=created_by_id
    )
    return saved_metric.id


def link_saved_metric(*, experiment_id: int, saved_metric_id: int, metadata: dict[str, Any] | None = None) -> int:
    """Attach a saved metric to an experiment, and return the link id.

    The metric is primary unless `metadata` holds `"type": "secondary"`.
    """
    link = ExperimentToSavedMetric.objects.create(
        experiment_id=experiment_id, saved_metric_id=saved_metric_id, metadata=metadata or {}
    )
    return link.id


def set_team_experiments_config(*, team_id: int, **fields: Any) -> None:
    """Write fields on the team's experiments config.

    A missing row is created with the fields in one insert, so its activity log records them as
    changes from the defaults, the same as a row created in the Django admin.
    """
    TeamExperimentsConfig.objects.update_or_create(team_id=team_id, defaults=fields)
