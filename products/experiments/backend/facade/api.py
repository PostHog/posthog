"""
Facade API for experiments product.

This module provides the public interface for creating and managing experiments
using framework-free DTOs, wrapping the existing ExperimentService.
"""

from django.db import IntegrityError, transaction
from django.db.models import Q

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment as ExperimentModel
from products.feature_flags.backend.models.feature_flag import FeatureFlag as FeatureFlagModel

from .contracts import (
    CreateExperimentInput,
    Experiment,
    PulseExperimentDraftInput,
    PulseExperimentDraftResult,
    PulseExperimentLifecycleResult,
)

_PULSE_DRAFT_PARAMETERS_KEY = "pulse_draft"
_PULSE_DRAFT_STATE = "draft"
_PULSE_EXPERIMENT_NAME_MAX_LENGTH = 400
_PULSE_TARGET_MAX_LENGTH = 300
_PULSE_DIRECTION_MAX_LENGTH = 50
_PULSE_EXPECTED_MOVEMENT_MAX_LENGTH = 1_000
_PULSE_DRAFT_VARIANTS = [
    {"key": "control", "name": "Control group", "rollout_percentage": 50},
    {"key": "test", "name": "Test variant", "rollout_percentage": 50},
]
_PULSE_DRAFT_FLAG_FILTERS: dict[str, object] = {
    "aggregation_group_type_index": None,
    "groups": [{"properties": [], "rollout_percentage": 0, "aggregation_group_type_index": None}],
    "holdout": None,
    "multivariate": {"variants": _PULSE_DRAFT_VARIANTS},
}


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


def create_pulse_experiment_draft(input: PulseExperimentDraftInput) -> PulseExperimentDraftResult:
    """Create or exactly replay one inert experiment draft for a durable Pulse artifact."""
    _validate_pulse_draft_input(input)
    team, actor = _resolve_pulse_draft_actor(input)
    feature_flag_key = _pulse_feature_flag_key(input.artifact_id.hex)

    try:
        with transaction.atomic():
            return _create_or_replay_pulse_experiment_draft(
                team=team,
                actor=actor,
                feature_flag_key=feature_flag_key,
                input=input,
            )
    except IntegrityError as err:
        with transaction.atomic():
            replay = _replay_pulse_experiment_draft(team=team, feature_flag_key=feature_flag_key, input=input)
            if replay is not None:
                return replay
        raise ValueError("Pulse experiment draft key collides with another resource.") from err


def get_pulse_experiment_lifecycle(*, team_id: int, experiment_id: int) -> PulseExperimentLifecycleResult:
    """Read the lifecycle of one team-owned Pulse experiment without changing it."""
    experiment = (
        ExperimentModel.objects.filter(id=experiment_id, team_id=team_id, deleted=False)
        .values("id", "start_date")
        .first()
    )
    if experiment is None:
        return PulseExperimentLifecycleResult(experiment_id=experiment_id, state="unknown", start_date=None)
    start_date = experiment["start_date"]
    return PulseExperimentLifecycleResult(
        experiment_id=experiment["id"],
        state="activated" if start_date is not None else "draft",
        start_date=start_date,
    )


def _create_or_replay_pulse_experiment_draft(
    *, team: Team, actor: User, feature_flag_key: str, input: PulseExperimentDraftInput
) -> PulseExperimentDraftResult:
    replay = _replay_pulse_experiment_draft(team=team, feature_flag_key=feature_flag_key, input=input)
    if replay is not None:
        return replay

    if (
        FeatureFlagModel.objects_including_soft_deleted.filter(team_id=team.id)
        .filter(Q(key=feature_flag_key) | Q(key__startswith=f"{feature_flag_key}:deleted:"))
        .exists()
    ):
        raise ValueError("Pulse experiment draft key collides with another resource.")

    experiment = ExperimentService(team=team, user=actor).create_experiment(
        name=input.title,
        description=_pulse_hypothesis(input),
        feature_flag_key=feature_flag_key,
        parameters={_PULSE_DRAFT_PARAMETERS_KEY: _pulse_provenance(input)},
        feature_flag_config={
            "filters": _PULSE_DRAFT_FLAG_FILTERS,
            "ensure_experience_continuity": False,
        },
        metrics=[],
        metrics_secondary=[],
        secondary_metrics=[],
        start_date=None,
        end_date=None,
        archived=False,
        deleted=False,
    )
    result = _replay_pulse_experiment_draft(team=team, feature_flag_key=feature_flag_key, input=input)
    if result is None or result.experiment_id != experiment.id:
        raise ValueError("created Pulse experiment draft does not match its durable claim")
    return result


def _replay_pulse_experiment_draft(
    *, team: Team, feature_flag_key: str, input: PulseExperimentDraftInput
) -> PulseExperimentDraftResult | None:
    experiment = (
        ExperimentModel.objects.select_related("feature_flag")
        .select_for_update()
        .filter(team_id=team.id, feature_flag__key=feature_flag_key)
        .first()
    )
    if experiment is None:
        return None
    if not _matches_pulse_experiment_draft(experiment=experiment, input=input, feature_flag_key=feature_flag_key):
        raise ValueError("Pulse experiment draft does not match its durable claim")
    return PulseExperimentDraftResult(
        experiment_id=experiment.id,
        feature_flag_id=experiment.feature_flag_id,
        url=f"/project/{team.id}/experiments/{experiment.id}",
    )


def _matches_pulse_experiment_draft(
    *, experiment: ExperimentModel, input: PulseExperimentDraftInput, feature_flag_key: str
) -> bool:
    flag = experiment.feature_flag
    return (
        experiment.team_id == input.team_id
        and experiment.name == input.title
        and experiment.description == _pulse_hypothesis(input)
        and experiment.parameters == {_PULSE_DRAFT_PARAMETERS_KEY: _pulse_provenance(input)}
        and experiment.archived is False
        and experiment.deleted is False
        and experiment.start_date is None
        and experiment.metrics == []
        and experiment.metrics_secondary == []
        and experiment.secondary_metrics == []
        and flag.key == feature_flag_key
        and flag.active is False
        and flag.archived is False
        and flag.deleted is False
        and flag.ensure_experience_continuity is False
        and flag.filters == _PULSE_DRAFT_FLAG_FILTERS
        and flag.variants == _PULSE_DRAFT_VARIANTS
    )


def _resolve_pulse_draft_actor(input: PulseExperimentDraftInput) -> tuple[Team, User]:
    team = Team.objects.filter(id=input.team_id).first()
    actor = User.objects.filter(id=input.actor_id).first()
    if team is None or actor is None or not actor.is_active:
        raise PermissionDenied("Pulse experiment draft access is no longer available.")
    access = UserAccessControl(user=actor, team=team)
    if not (
        access.has_project_access
        and access.check_access_level_for_resource("experiment", "editor")
        and access.check_access_level_for_resource("feature_flag", "editor")
    ):
        raise PermissionDenied("Pulse experiment draft access is no longer available.")
    return team, actor


def _validate_pulse_draft_input(input: PulseExperimentDraftInput) -> None:
    bounded_text = (
        (input.title, _PULSE_EXPERIMENT_NAME_MAX_LENGTH),
        (input.target, _PULSE_TARGET_MAX_LENGTH),
        (input.metric_direction, _PULSE_DIRECTION_MAX_LENGTH),
        (input.expected_metric_movement, _PULSE_EXPECTED_MOVEMENT_MAX_LENGTH),
    )
    if any(not isinstance(value, str) or not value.strip() or len(value) > maximum for value, maximum in bounded_text):
        raise ValueError("Pulse experiment draft input is invalid.")


def _pulse_feature_flag_key(artifact_hex: str) -> str:
    return f"pulse-experiment-{artifact_hex}"


def _pulse_provenance(input: PulseExperimentDraftInput) -> dict[str, int | str]:
    return {"artifact_id": str(input.artifact_id), "state": _PULSE_DRAFT_STATE, "team_id": input.team_id}


def _pulse_hypothesis(input: PulseExperimentDraftInput) -> str:
    return (
        f"Hypothesis: For {input.target}, the expected metric movement is "
        f"{input.metric_direction}: {input.expected_metric_movement}."
    )


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
