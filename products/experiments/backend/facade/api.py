"""
Facade API for experiments product.

This module provides the public interface for creating and managing experiments
using framework-free DTOs, wrapping the existing ExperimentService.
"""

from decimal import Decimal
from typing import Literal

from django.db import transaction

from rest_framework.exceptions import ValidationError

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import (
    Experiment as ExperimentModel,
    ExperimentMetricResult,
)
from products.experiments.backend.pulse_experiment_draft_service import (
    create_pulse_experiment_draft_experiment as create_pulse_experiment_draft_experiment_model,
    resolve_or_create_pulse_experiment_draft_flag as resolve_or_create_pulse_experiment_draft_flag_model,
)

from .contracts import (
    CreateExperimentInput,
    Experiment,
    FeatureFlag,
    PulseExperimentDraftInput,
    PulseExperimentLifecycleDTO,
)


@frozen
class _PulsePrimaryMetricResult:
    state: Literal["not_ready", "measured", "inconclusive"]
    observed_value: Decimal | None = None
    delta: Decimal | None = None
    confidence: Decimal | None = None
    verdict: Literal["improved", "flat", "regressed", "inconclusive"] | None = None


def create_experiment(*, team: Team, user: User, input_dto: CreateExperimentInput) -> Experiment:
    """
    Create a new experiment.

    Transactional safety is provided by ExperimentService.create_experiment.

    Args:
        team: Team creating the experiment
        user: User creating the experiment
        input_dto: Experiment creation input with all configuration

    Returns:
        Experiment DTO

    Raises:
        ValidationError: If validation fails in service layer
    """

    # Load holdout if ID provided
    from products.experiments.backend.models.experiment import ExperimentHoldout

    holdout = None
    if input_dto.holdout_id is not None:
        try:
            holdout = ExperimentHoldout.objects.get(id=input_dto.holdout_id, team_id=team.id)
        except ExperimentHoldout.DoesNotExist:
            raise ValidationError(f"Holdout with id {input_dto.holdout_id} does not exist for this team")

    # Convert tuple to list for ordering fields (DTO uses tuple for immutability)
    primary_metrics_ordered_uuids = list(input_dto.metrics_ordering) if input_dto.metrics_ordering else None
    secondary_metrics_ordered_uuids = (
        list(input_dto.secondary_metrics_ordering) if input_dto.secondary_metrics_ordering else None
    )

    # Call existing service (already @transaction.atomic)
    service = ExperimentService(team=team, user=user)
    experiment_model = service.create_experiment(
        name=input_dto.name,
        feature_flag_key=input_dto.feature_flag_key,
        description=input_dto.description,
        type=input_dto.type,
        parameters=input_dto.parameters,
        feature_flag_config=input_dto.feature_flag_config,
        running_time_calculation=input_dto.running_time_calculation,
        excluded_variants=input_dto.excluded_variants,
        metrics=input_dto.metrics,
        metrics_secondary=input_dto.metrics_secondary,
        secondary_metrics=input_dto.secondary_metrics,
        stats_config=input_dto.stats_config,
        exposure_criteria=input_dto.exposure_criteria,
        holdout=holdout,
        saved_metrics_ids=input_dto.saved_metrics_ids,
        start_date=input_dto.start_date,
        end_date=input_dto.end_date,
        primary_metrics_ordered_uuids=primary_metrics_ordered_uuids,
        secondary_metrics_ordered_uuids=secondary_metrics_ordered_uuids,
        create_in_folder=input_dto.create_in_folder,
        filters=input_dto.filters,
        scheduling_config=input_dto.scheduling_config,
        only_count_matured_users=input_dto.only_count_matured_users,
        archived=input_dto.archived,
        deleted=input_dto.deleted,
        conclusion=input_dto.conclusion,
        conclusion_comment=input_dto.conclusion_comment,
        repository=input_dto.repository,
        serializer_context=input_dto.serializer_context,
        allow_unknown_events=input_dto.allow_unknown_events,
    )

    # Convert model to DTO
    return _experiment_model_to_dto(experiment_model)


def create_pulse_experiment_draft(
    *, team: Team, user: User, feature_flag_key: str, input_dto: PulseExperimentDraftInput
) -> Experiment:
    """Create an inert, new-flag experiment draft from a server-owned Pulse proposal."""
    flag = resolve_or_create_pulse_experiment_draft_flag(
        team=team,
        user=user,
        feature_flag_key=feature_flag_key,
        input_dto=input_dto,
    )
    with transaction.atomic():
        return create_pulse_experiment_draft_experiment(
            team=team,
            user=user,
            feature_flag_id=flag.id,
            feature_flag_key=flag.key,
            input_dto=input_dto,
        )


def get_pulse_experiment_lifecycle(*, team_id: int, experiment_id: int) -> PulseExperimentLifecycleDTO | None:
    """Return only model-owned lifecycle and cached primary-result state for one experiment."""
    experiment = ExperimentModel.objects.filter(id=experiment_id, team_id=team_id).first()
    if experiment is None:
        return None
    state = _pulse_experiment_state(experiment)
    primary_metric_result = _pulse_primary_metric_result(experiment)
    return PulseExperimentLifecycleDTO(
        experiment_id=experiment.id,
        state=state,
        launched_at=experiment.start_date,
        ended_at=experiment.end_date,
        result_state=primary_metric_result.state,
        observed_value=primary_metric_result.observed_value,
        delta=primary_metric_result.delta,
        confidence=primary_metric_result.confidence,
        verdict=primary_metric_result.verdict,
        experiment_path=f"/experiments/{experiment.id}",
    )


def _pulse_experiment_state(experiment: ExperimentModel) -> Literal["draft", "launched", "ended", "deleted"]:
    if experiment.deleted:
        return "deleted"
    if experiment.end_date is not None:
        return "ended"
    if experiment.start_date is not None:
        return "launched"
    return "draft"


def _pulse_primary_metric_result(
    experiment: ExperimentModel,
) -> _PulsePrimaryMetricResult:
    """Expose only a proven scalar outcome contract; cached query payloads are otherwise inconclusive."""
    metric_uuid = _primary_metric_uuid(experiment)
    if metric_uuid is None:
        return _PulsePrimaryMetricResult(state="not_ready")
    result = (
        ExperimentMetricResult.objects.filter(
            experiment=experiment,
            metric_uuid=metric_uuid,
            status=ExperimentMetricResult.Status.COMPLETED,
        )
        .order_by("-completed_at", "-query_to")
        .first()
    )
    if result is None:
        return _PulsePrimaryMetricResult(state="not_ready")
    return _PulsePrimaryMetricResult(state="not_ready")


def _primary_metric_uuid(experiment: ExperimentModel) -> str | None:
    ordered = experiment.primary_metrics_ordered_uuids
    if isinstance(ordered, list) and ordered and isinstance(ordered[0], str):
        return ordered[0]
    metrics = experiment.metrics
    if not isinstance(metrics, list) or not metrics or not isinstance(metrics[0], dict):
        return None
    metric_uuid = metrics[0].get("uuid")
    return metric_uuid if isinstance(metric_uuid, str) else None


def resolve_or_create_pulse_experiment_draft_flag(
    *, team: Team, user: User, feature_flag_key: str, input_dto: PulseExperimentDraftInput
) -> FeatureFlag:
    """Resolve the one exact inert feature flag that belongs to a Pulse proposal."""
    flag = resolve_or_create_pulse_experiment_draft_flag_model(
        team=team,
        user=user,
        feature_flag_key=feature_flag_key,
        input_dto=input_dto,
    )
    return FeatureFlag(
        id=flag.id,
        key=flag.key,
        active=flag.active,
        created_at=flag.created_at,
        name=flag.name,
    )


def create_pulse_experiment_draft_experiment(
    *,
    team: Team,
    user: User,
    feature_flag_id: int,
    feature_flag_key: str,
    input_dto: PulseExperimentDraftInput,
) -> Experiment:
    """Create the experiment alongside the caller's durable Artifact finalization."""
    experiment_model = create_pulse_experiment_draft_experiment_model(
        team=team,
        user=user,
        feature_flag_id=feature_flag_id,
        feature_flag_key=feature_flag_key,
        input_dto=input_dto,
    )
    return _experiment_model_to_dto(experiment_model)


def _experiment_model_to_dto(experiment: ExperimentModel) -> Experiment:
    """Convert Django model to DTO."""
    return Experiment(
        id=experiment.id,
        name=experiment.name,
        description=experiment.description or None,
        feature_flag_id=experiment.feature_flag_id,
        feature_flag_key=experiment.feature_flag.key,
        is_draft=experiment.start_date is None,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
    )
