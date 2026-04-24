"""
Facade API for experiment saved metrics.

This module provides the public interface for creating and managing saved metrics
using framework-free DTOs, wrapping the existing ExperimentSavedMetricService.
"""

from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.models.team import Team
from posthog.models.user import User

from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService
from products.experiments.backend.models.experiment import ExperimentSavedMetric as SavedMetricModel

from .saved_metric_contracts import (
    CreateSavedMetricInput,
    ExperimentSavedMetric,
    ListSavedMetricsInput,
    UpdateSavedMetricInput,
)


def create_saved_metric(*, team: Team, user: User, input_dto: CreateSavedMetricInput) -> SavedMetricModel:
    """
    Create a new saved metric.

    Transactional safety is provided by ExperimentSavedMetricService.create_saved_metric.

    Args:
        team: Team creating the saved metric
        user: User creating the saved metric
        input_dto: Saved metric creation input

    Returns:
        ExperimentSavedMetric model instance

    Raises:
        ValidationError: If validation fails in service layer
    """
    service = ExperimentSavedMetricService(team=team, user=user)
    metric_model = service.create_saved_metric(
        name=input_dto.name,
        query=input_dto.query,
        description=input_dto.description,
    )

    # Note: Tags are handled separately by the serializer (not part of service create)
    # This is consistent with existing pattern in ExperimentSavedMetricSerializer.create()

    return metric_model


def update_saved_metric(
    *, team: Team, user: User, saved_metric_id: int, input_dto: UpdateSavedMetricInput
) -> SavedMetricModel:
    """
    Update a saved metric.

    Transactional safety is provided by ExperimentSavedMetricService.update_saved_metric.

    Args:
        team: Team owning the saved metric
        user: User updating the saved metric
        saved_metric_id: ID of saved metric to update
        input_dto: Update data (only non-None fields will be updated)

    Returns:
        ExperimentSavedMetric model instance

    Raises:
        ValidationError: If validation fails or saved metric doesn't exist
    """
    # Load the saved metric
    metric_model = SavedMetricModel.objects.get(id=saved_metric_id, team_id=team.id)

    # Build update dict from DTO (only include non-None fields)
    update_data: dict[str, Any] = {}
    if input_dto.name is not None:
        update_data["name"] = input_dto.name
    if input_dto.description is not None:
        update_data["description"] = input_dto.description
    if input_dto.query is not None:
        update_data["query"] = input_dto.query

    # Call service
    service = ExperimentSavedMetricService(team=team, user=user)
    updated_model = service.update_saved_metric(metric_model, update_data)

    return updated_model


def delete_saved_metric(*, team: Team, user: User, saved_metric: SavedMetricModel) -> None:
    """
    Delete a saved metric.

    Transactional safety is provided by ExperimentSavedMetricService.delete_saved_metric.

    Args:
        team: Team owning the saved metric
        user: User deleting the saved metric
        saved_metric: SavedMetric model instance to delete

    Raises:
        ValidationError: If saved metric doesn't belong to team
    """
    # Verify ownership
    if saved_metric.team_id != team.id:
        raise ValidationError("Saved metric does not belong to this team")

    # Call service
    service = ExperimentSavedMetricService(team=team, user=user)
    service.delete_saved_metric(saved_metric)


def list_saved_metrics(*, team: Team, user: User, input_dto: ListSavedMetricsInput) -> list[ExperimentSavedMetric]:
    """
    List all saved metrics for a team.

    Args:
        team: Team to list saved metrics for
        user: User requesting the list
        input_dto: List parameters (currently unused, for future filtering)

    Returns:
        List of ExperimentSavedMetric DTOs ordered by name (case-insensitive)
    """
    from django.db.models.functions import Lower

    metrics = SavedMetricModel.objects.filter(team=team).order_by(Lower("name")).all()

    return [_saved_metric_model_to_dto(metric) for metric in metrics]


def get_saved_metric(*, team: Team, user: User, saved_metric_id: int) -> ExperimentSavedMetric:
    """
    Retrieve a single saved metric.

    Args:
        team: Team owning the saved metric
        user: User requesting the saved metric
        saved_metric_id: ID of saved metric to retrieve

    Returns:
        ExperimentSavedMetric DTO

    Raises:
        DoesNotExist: If saved metric doesn't exist or doesn't belong to team
    """
    metric_model = SavedMetricModel.objects.get(id=saved_metric_id, team_id=team.id)
    return _saved_metric_model_to_dto(metric_model)


def _saved_metric_model_to_dto(metric: SavedMetricModel) -> ExperimentSavedMetric:
    """Convert Django model to DTO."""
    return ExperimentSavedMetric(
        id=metric.id,
        name=metric.name,
        query=metric.query,
        description=metric.description,
        created_by_id=metric.created_by_id,
        created_at=metric.created_at,
        updated_at=metric.updated_at,
        tags=None,  # Tags loaded separately via serializer
    )
