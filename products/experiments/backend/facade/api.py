"""
Facade API for experiments product.

This module provides the public interface for creating and managing experiments
using framework-free DTOs, wrapping the existing ExperimentService.
"""

import dataclasses
from collections import defaultdict
from collections.abc import Collection, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError

import pydantic
import structlog

from posthog.schema import ExperimentEventExposureConfig

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.models.user import User

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.flag_enrollment import enrolled_people_by_flag
from products.experiments.backend.health.inputs_payload import health_inputs_payload
from products.experiments.backend.health.loader import load_experiment_health_context, load_experiment_health_inputs
from products.experiments.backend.health.registry import (
    EXPERIMENT_HEALTH_CHECKS,
    evaluate as evaluate_health,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    get_exposure_event_and_property,
    is_default_exposure_config,
    normalize_to_exposure_criteria,
    resolve_default_exposure_event,
)
from products.experiments.backend.metric_calculation.config import (
    build_primary_calculation_configs,
    calculation_metric_name,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.models.experiment import (
    Experiment as ExperimentModel,
    flag_has_live_experiment as _flag_has_live_experiment,
)
from products.experiments.backend.models.team_experiments_config import (
    TeamExperimentsConfig,
    validate_recalculation_times as _validate_stored_recalculation_times,
)
from products.experiments.backend.running_time_target import load_running_time_target
from products.experiments.stats.shared.enums import DifferenceType

from .contracts import (
    CreateExperimentInput,
    DigestCompletedExperiment,
    DigestLaunchedExperiment,
    EndedExperiment,
    Experiment,
    ExperimentDetectableEffectCheckpoint,
    ExperimentHealth,
    ExperimentHealthReaderAccess,
    ExperimentRunningTimeOutlook,
    ExperimentRunningTimeTarget,
    ExperimentValidationError,
    LinkedExperiment,
    RunningExperiment,
    RunningTimeMode,
    StoredArmResult,
    StoredPrimaryResult,
    TeamExperimentsSettings,
    TeamExperimentsSettingsUpdate,
    Unset,
)
from .enums import MAX_DEFAULT_CONFIDENCE_LEVEL, MIN_DEFAULT_CONFIDENCE_LEVEL

logger = structlog.get_logger(__name__)


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
        ExperimentValidationError: If the holdout does not exist for this team
        rest_framework.exceptions.ValidationError: If validation fails in service layer
    """

    # Load holdout if ID provided
    from products.experiments.backend.models.experiment import ExperimentHoldout

    holdout = None
    if input_dto.holdout_id is not None:
        try:
            holdout = ExperimentHoldout.objects.get(id=input_dto.holdout_id, team_id=team.id)
        except ExperimentHoldout.DoesNotExist:
            raise ExperimentValidationError(f"Holdout with id {input_dto.holdout_id} does not exist for this team")

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


def count_running_experiments_on_feature_flag_called(organization_id: UUID) -> int:
    """Count the organization's running experiments that count exposures on $feature_flag_called.

    Those exposures come from the events table, so they stop when ingestion stops writing
    $feature_flag_called to events.
    """
    experiments = (
        ExperimentModel.objects.filter(
            team__organization_id=organization_id, start_date__isnull=False, end_date__isnull=True, archived=False
        )
        .exclude(deleted=True)
        .select_related("team", "feature_flag")
    )
    count = 0
    for experiment in experiments:
        exposure_event, _ = get_exposure_event_and_property(
            experiment.feature_flag.key,
            experiment.exposure_criteria,
            default_exposure_event=resolve_default_exposure_event(experiment.team, experiment.start_date),
        )
        count += exposure_event == DEFAULT_EXPOSURE_EVENT
    return count


def get_experiment_health(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> ExperimentHealth:
    """The findings and the result of each health check that reads the experiment, its flag, its linked metrics,
    and the changes of the flag since launch and the flag's recent calls, as far as `reader_access` allows. The
    metric queries compile with `user`'s warehouse access."""
    context = load_experiment_health_context(
        team_id=team_id, experiment_id=experiment_id, reader_access=reader_access, user=user
    )
    return evaluate_health(context, EXPERIMENT_HEALTH_CHECKS)


def get_experiment_health_inputs(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> dict[str, Any]:
    """Everything the health checks read for the reader, as plain data in the shape of the staff `health_inputs`
    response: the checks' context, the exposure query's answer that the exposure checks read, and the project's
    experiment defaults and SDK profile."""
    inputs = load_experiment_health_inputs(
        team_id=team_id, experiment_id=experiment_id, reader_access=reader_access, user=user
    )
    return health_inputs_payload(inputs)


def get_stored_primary_result(*, team_id: int, experiment_id: int) -> StoredPrimaryResult | None:
    """The current stored result of the experiment's primary metric. It reads Postgres only, not ClickHouse.

    None for an experiment that reports absolute differences: the calculation key leaves out the difference type,
    so the stored interval can be in either unit."""
    experiment = ExperimentModel.objects.filter(team_id=team_id, pk=experiment_id, deleted=False).first()
    config = next(iter(build_primary_calculation_configs(experiment)), None) if experiment else None
    if experiment is None or config is None or config.settings.stats.difference_type == DifferenceType.ABSOLUTE:
        return None
    stats = MetricResultStore(experiment_id=experiment_id).current_result(config)
    if stats is None:
        return None
    base = stats.baseline.mean
    definition = config.definition
    return StoredPrimaryResult(
        metric_name=calculation_metric_name(experiment, config),
        metric_type=definition.get("metric_type"),
        proportion=definition.get("metric_type") == "funnel" or definition.get("threshold") is not None,
        goal=definition.get("goal"),
        baseline=StoredArmResult(key=stats.baseline.key, number_of_samples=stats.baseline.number_of_samples, mean=base),
        variants=tuple(
            StoredArmResult(
                key=variant.key,
                number_of_samples=variant.number_of_samples,
                mean=variant.mean,
                change=variant.interval.midpoint if variant.interval and base and base > 0 else None,
                significant=variant.significant,
            )
            for variant in stats.variants
        ),
    )


def get_running_time_target(
    *, team_id: int, experiment_id: int, mode: RunningTimeMode | None = None
) -> ExperimentRunningTimeTarget:
    """The target sample of the experiment's running time estimate, with what the experiment can detect over time.
    `mode` replaces the saved one, so that the page can show the automatic target while the user switches to it."""
    experiment = ExperimentModel.objects.select_related("feature_flag").get(team_id=team_id, id=experiment_id)
    target = load_running_time_target(experiment, mode=mode)
    outlook = target.outlook
    return ExperimentRunningTimeTarget(
        minimum_detectable_effect=target.minimum_detectable_effect,
        recommended_sample_size=target.recommended_sample_size,
        current_sample_size=target.current_sample_size,
        outlook=ExperimentRunningTimeOutlook(
            days_since_launch=outlook.days_since_launch,
            exposures_per_day=outlook.exposures_per_day,
            detectable_effect_now=outlook.detectable_effect_now,
            upcoming_checkpoints=tuple(
                ExperimentDetectableEffectCheckpoint(
                    weeks_since_launch=checkpoint.weeks_since_launch,
                    detectable_effect=checkpoint.detectable_effect,
                )
                for checkpoint in outlook.upcoming_checkpoints
            ),
            reachable_effect=outlook.reachable_effect,
        )
        if outlook
        else None,
    )


def list_ended_experiments_without_conclusion(
    *, team_id: int, user_id: int, since: datetime, limit: int
) -> list[EndedExperiment]:
    rows = (
        ExperimentModel.objects.filter(
            team_id=team_id,
            created_by_id=user_id,
            end_date__gte=since,
            conclusion__isnull=True,
            archived=False,
        )
        .exclude(deleted=True)
        .order_by("-end_date")
        .values_list("id", "name", "end_date")[:limit]
    )
    return [EndedExperiment(id=id, name=name, ended_at=ended_at) for id, name, ended_at in rows]


def _exposes_on_flag_calls(experiment_id: int, exposure_criteria: dict | None) -> bool:
    try:
        criteria = normalize_to_exposure_criteria(exposure_criteria)
    except pydantic.ValidationError:
        logger.warning("experiment_exposure_criteria_invalid", experiment_id=experiment_id, exc_info=True)
        return False
    return criteria is None or (
        criteria.activation_config is None
        and is_default_exposure_config(criteria.exposure_config)
        and not (
            isinstance(criteria.exposure_config, ExperimentEventExposureConfig) and criteria.exposure_config.properties
        )
    )


def list_running_experiments(
    *, team_id: int, user_id: int, started_after: datetime | None, started_before: datetime, limit: int
) -> list[RunningExperiment]:
    experiments = ExperimentModel.objects.filter(
        team_id=team_id,
        created_by_id=user_id,
        start_date__lte=started_before,
        end_date__isnull=True,
        archived=False,
    ).exclude(deleted=True)
    if started_after is not None:
        experiments = experiments.filter(start_date__gt=started_after)
    rows = experiments.order_by("-start_date").values_list(
        "id", "name", "start_date", "feature_flag__key", "exposure_criteria"
    )[:limit]
    return [
        RunningExperiment(id=id, name=name, started_at=started_at, flag_key=flag_key)
        for id, name, started_at, flag_key, exposure_criteria in rows
        if _exposes_on_flag_calls(id, exposure_criteria)
    ]


def count_enrolled_people(*, team: Team, user: User, flag_keys: list[str]) -> dict[str, int]:
    return enrolled_people_by_flag(team, user, flag_keys)


def team_has_launched_experiments(team_id: int) -> bool:
    """Whether the team has a running or stopped experiment, deleted and archived ones included. Experiments are saved
    on the project's root team, so pass that team's id."""
    # `team=` matches the id exactly. RootTeamQuerySet rewrites a `team_id=` filter to the project's root team.
    return ExperimentModel.objects.filter(
        team=team_id, status__in=[ExperimentModel.Status.RUNNING, ExperimentModel.Status.STOPPED]
    ).exists()


def experiment_flag_ids(team_ids: Collection[int], *, include_deleted: bool) -> set[int]:
    """Ids of the flags that the teams' experiments use, archived experiments included."""
    experiments = ExperimentModel.objects.filter(team_id__in=team_ids)
    if not include_deleted:
        experiments = experiments.filter(deleted=False)
    return set(experiments.values_list("feature_flag_id", flat=True))


def list_launched_experiments_for_digest(
    *, period_start: datetime, period_end: datetime, team_ids: range
) -> list[DigestLaunchedExperiment]:
    """Experiments of the teams in `team_ids` that started after `period_start` and by `period_end`, and did not also
    end in that period. Deleted and archived experiments are included, in no set order."""
    rows = (
        ExperimentModel.objects.filter(
            team_id__gte=team_ids.start,
            team_id__lt=team_ids.stop,
            start_date__gt=period_start,
            start_date__lte=period_end,
        )
        .exclude(end_date__gt=period_start, end_date__lte=period_end)
        .values_list("team_id", "id", "name", "start_date")
    )
    return [
        DigestLaunchedExperiment(team_id=team_id, id=id, name=name, start_date=start_date)
        for team_id, id, name, start_date in rows
    ]


def list_completed_experiments_for_digest(
    *, period_start: datetime, period_end: datetime, team_ids: range
) -> list[DigestCompletedExperiment]:
    """Experiments of the teams in `team_ids` that ended after `period_start` and by `period_end`. Deleted and
    archived experiments are included, in no set order."""
    rows = ExperimentModel.objects.filter(
        team_id__gte=team_ids.start,
        team_id__lt=team_ids.stop,
        end_date__gt=period_start,
        end_date__lte=period_end,
    ).values_list("team_id", "id", "name", "start_date", "end_date")
    return [
        DigestCompletedExperiment(team_id=team_id, id=id, name=name, start_date=start_date, end_date=end_date)
        for team_id, id, name, start_date, end_date in rows
    ]


def list_precomputation_enabled_team_ids(team_ids: Collection[int] | None = None) -> set[int]:
    """Ids of the teams that have experiment precomputation enabled, among `team_ids` when it is given."""
    configs = TeamExperimentsConfig.objects.filter(experiment_precomputation_enabled=True)
    if team_ids is not None:
        configs = configs.filter(team_id__in=team_ids)
    return set(configs.values_list("team_id", flat=True))


def _team_experiments_config(team_id: int) -> TeamExperimentsConfig:
    try:
        # Join the team because the activity log on every save and the repository check read `config.team`.
        # `select_related` builds the team columns from the model rather than through `TeamManager`, so re-apply
        # its defer. Without it every settings read and update loads the deprecated taxonomy columns, which TOAST
        # out to megabytes per team.
        return (
            TeamExperimentsConfig.objects.select_related("team")
            .defer(*(f"team__{attr}" for attr in DEPRECATED_ATTRS))
            .get(team_id=team_id)
        )
    except TeamExperimentsConfig.DoesNotExist:
        return get_or_create_team_extension(Team.objects.get(id=team_id), TeamExperimentsConfig)


def set_precomputation_enabled(*, team_id: int, enabled: bool) -> None:
    config = _team_experiments_config(team_id)
    config.experiment_precomputation_enabled = enabled
    # A human toggling precomputation must stick: the auto-enrollment job only
    # writes when precomputation_enabled_set_by is null or "auto".
    config.precomputation_enabled_set_by = TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL
    config.save(update_fields=["experiment_precomputation_enabled", "precomputation_enabled_set_by"])


def _to_team_experiments_settings(config: TeamExperimentsConfig) -> TeamExperimentsSettings:
    times = config.experiment_recalculation_times
    return TeamExperimentsSettings(
        experiment_recalculation_times=None if times is None else tuple(times),
        default_experiment_confidence_level=config.default_experiment_confidence_level,
        default_experiment_stats_method=config.default_experiment_stats_method,
        experiment_precomputation_enabled=config.experiment_precomputation_enabled,
        default_only_count_matured_users=config.default_only_count_matured_users,
        default_cuped_enabled=config.default_cuped_enabled,
        default_cuped_lookback_days=config.default_cuped_lookback_days,
        default_minimum_detectable_effect=config.default_minimum_detectable_effect,
        default_sequential_testing_enabled=config.default_sequential_testing_enabled,
        default_sequential_tuning_parameter=config.default_sequential_tuning_parameter,
        flag_cleanup_repository=config.flag_cleanup_repository,
    )


def get_team_experiments_settings(team_id: int) -> TeamExperimentsSettings:
    """The first read creates the team's settings row with the defaults."""
    return _to_team_experiments_settings(_team_experiments_config(team_id))


def validate_recalculation_times(times: Sequence[str] | None) -> None:
    try:
        _validate_stored_recalculation_times(None if times is None else list(times))
    except DjangoValidationError as error:
        raise ExperimentValidationError(error.messages[0], field="experiment_recalculation_times") from error


def _connected_cleanup_repository(team: Team, repository: str | None) -> str | None:
    # Keeps the sandbox/LLM runtime the repo-selection module pulls in off the
    # request import path.
    from products.tasks.backend.facade import repo_selection as tasks_repo_selection  # noqa: PLC0415

    if not repository:
        return None
    parts = repository.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ExperimentValidationError(
            "Repository must be in the format organization/repository", field="flag_cleanup_repository"
        )
    repository = repository.lower()
    # Reject repos outside the team's GitHub installation now rather than storing a
    # default the cleanup resolution would silently ignore.
    github = tasks_repo_selection.resolve_team_github_integration(team.id, team=team, team_only=True)
    cached = {
        full_name.lower()
        for repo in (github.list_all_cached_repositories(max_repos=1000) if github else [])
        if (full_name := repo.get("full_name"))
    }
    if repository not in cached:
        raise ExperimentValidationError(
            "This repository is not connected to the project's GitHub integration.", field="flag_cleanup_repository"
        )
    return repository


def update_team_experiments_settings(*, team_id: int, update: TeamExperimentsSettingsUpdate) -> TeamExperimentsSettings:
    """Applies the settings that `update` sets, with the checks of the project settings endpoint. Raises
    ExperimentValidationError for the first setting that fails, with the setting's name in `field`."""
    config = _team_experiments_config(team_id)
    changes: dict[str, object] = {
        setting.name: getattr(update, setting.name)
        for setting in dataclasses.fields(update)
        if not isinstance(getattr(update, setting.name), Unset)
    }
    if not isinstance(times := update.experiment_recalculation_times, Unset):
        validate_recalculation_times(times)
        # The JSON column holds a list. A tuple never equals the stored list, so the activity log would report an
        # unchanged schedule as a change.
        changes["experiment_recalculation_times"] = None if times is None else list(times)
    if isinstance(level := update.default_experiment_confidence_level, Decimal):
        if level < MIN_DEFAULT_CONFIDENCE_LEVEL:
            raise ExperimentValidationError(
                f"Ensure this value is greater than or equal to {MIN_DEFAULT_CONFIDENCE_LEVEL}.",
                field="default_experiment_confidence_level",
            )
        if level > MAX_DEFAULT_CONFIDENCE_LEVEL:
            raise ExperimentValidationError(
                f"Ensure this value is less than or equal to {MAX_DEFAULT_CONFIDENCE_LEVEL}.",
                field="default_experiment_confidence_level",
            )
    for name, value in changes.items():
        setattr(config, name, value)
    try:
        config.clean_fields(exclude={field.name for field in TeamExperimentsConfig._meta.fields} - changes.keys())
    except DjangoValidationError as error:
        name, messages = next(iter(error.message_dict.items()))
        raise ExperimentValidationError(messages[0], field=name) from error
    if not isinstance(repository := update.flag_cleanup_repository, Unset):
        config.flag_cleanup_repository = _connected_cleanup_repository(config.team, repository)
    config.save()
    return _to_team_experiments_settings(config)


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


def flag_has_live_experiment(feature_flag_id: int) -> bool:
    """Whether an experiment that is not deleted uses the flag. Flag ids are unique across teams, so the id scopes
    the read."""
    return _flag_has_live_experiment(feature_flag_id)


def live_experiments_by_flag(feature_flag_ids: Collection[int]) -> dict[int, tuple[LinkedExperiment, ...]]:
    """The experiments that are not deleted on each of the flags, archived ones included, keyed by flag id, in no set
    order. A flag without one has no key. Flag ids are unique across teams, so pass ids from a team-scoped read."""
    experiments: defaultdict[int, list[LinkedExperiment]] = defaultdict(list)
    for experiment in ExperimentModel.objects.filter(deleted=False, feature_flag_id__in=feature_flag_ids).only(
        "id", "name", "feature_flag_id", "start_date", "end_date"
    ):
        experiments[experiment.feature_flag_id].append(
            LinkedExperiment(id=experiment.id, name=experiment.name, is_running=experiment.is_running)
        )
    return {flag_id: tuple(linked) for flag_id, linked in experiments.items()}
