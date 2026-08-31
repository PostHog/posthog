"""Create the narrowly scoped, inert experiment drafts that Pulse may propose."""

from typing import cast

from django.db import transaction

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.contracts import (
    PulseExperimentDraftInput,
    PulseExperimentMetricRef,
    PulseExperimentVariant,
)
from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.warehouse_access_control import enforce_warehouse_metric_access
from products.feature_flags.backend.facade.api import create_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag

MAX_PULSE_EXPERIMENT_NAME_LENGTH = 400
MAX_PULSE_EXPERIMENT_DESCRIPTION_LENGTH = 3000
MAX_PULSE_VARIANTS = 5
MAX_PULSE_METRICS = 10


def resolve_or_create_pulse_experiment_draft_flag(
    *, team: Team, user: User, feature_flag_key: str, input_dto: PulseExperimentDraftInput
) -> FeatureFlag:
    """Resolve or create exactly the server-owned inert flag for a Pulse proposal.

    The feature-flag write deliberately happens outside a caller transaction.
    ``create_flag`` must remain outside an atomic block so an ApprovalRequired exception
    retains its ChangeRequest. An existing flag is accepted only when every persisted
    field Pulse owns still exactly matches this proposal and the acting user created it.
    """
    _validate_access(team=team, user=user)
    _validate_input(feature_flag_key=feature_flag_key, input_dto=input_dto)
    _validate_metric_references(team=team, user=user, input_dto=input_dto)

    existing_flag = FeatureFlag.objects_including_soft_deleted.filter(team_id=team.id, key=feature_flag_key).first()
    if existing_flag is not None:
        _assert_exact_pulse_draft_flag(
            feature_flag=existing_flag,
            team=team,
            user=user,
            feature_flag_key=feature_flag_key,
            input_dto=input_dto,
        )
        return existing_flag

    try:
        return create_flag(
            _new_inert_feature_flag_data(feature_flag_key=feature_flag_key, input_dto=input_dto),
            team=team,
            user=user,
        )
    except ValidationError:
        raced_flag = FeatureFlag.objects_including_soft_deleted.filter(team_id=team.id, key=feature_flag_key).first()
        if raced_flag is None:
            raise
        _assert_exact_pulse_draft_flag(
            feature_flag=raced_flag,
            team=team,
            user=user,
            feature_flag_key=feature_flag_key,
            input_dto=input_dto,
        )
        return raced_flag


def create_pulse_experiment_draft_experiment(
    *,
    team: Team,
    user: User,
    feature_flag_id: int,
    feature_flag_key: str,
    input_dto: PulseExperimentDraftInput,
) -> Experiment:
    """Create the experiment half of a Pulse draft in the caller's atomic transaction.

    Callers use this while holding their Artifact reservation transaction. The function
    locks and revalidates the exact flag before adding the experiment, so the Artifact
    and experiment either commit together or no experiment is created.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Pulse experiment creation must run inside the caller's transaction.")

    _validate_access(team=team, user=user)
    _validate_input(feature_flag_key=feature_flag_key, input_dto=input_dto)

    service = ExperimentService(team=team, user=user)
    metrics = [_metric_ref_to_metric(input_dto.primary_metric)]
    metrics_secondary = [_metric_ref_to_metric(metric) for metric in input_dto.secondary_metrics]
    metrics = cast(list[dict[str, object]], service._assign_uuids_to_metrics(metrics))
    metrics_secondary = cast(list[dict[str, object]], service._assign_uuids_to_metrics(metrics_secondary))
    service.validate_experiment_metrics(metrics)
    service.validate_experiment_metrics(metrics_secondary)
    service.validate_metric_action_ids(metrics, team.id)
    service.validate_metric_action_ids(metrics_secondary, team.id)
    service.validate_metric_event_names(metrics)
    service.validate_metric_event_names(metrics_secondary)
    enforce_warehouse_metric_access([*metrics, *metrics_secondary], team=team, user=user)

    team_config = service._get_team_experiments_config()
    stats_config = service._apply_stats_config_defaults(None, team_config)
    exposure_criteria = service._apply_exposure_criteria_defaults(None)
    only_count_matured_users = team_config.default_only_count_matured_users
    for metric in [*metrics, *metrics_secondary]:
        metric["fingerprint"] = compute_metric_fingerprint(
            metric,
            None,
            "bayesian" if stats_config is None else stats_config.get("method", "bayesian"),
            exposure_criteria,
            only_count_matured_users=only_count_matured_users,
            excluded_variants=None,
        )

    try:
        locked_flag = FeatureFlag.objects.select_for_update().get(pk=feature_flag_id, team_id=team.id)
    except FeatureFlag.DoesNotExist:
        raise ValidationError("The authoritative feature flag does not exist for this project.")
    _assert_exact_pulse_draft_flag(
        feature_flag=locked_flag,
        team=team,
        user=user,
        feature_flag_key=feature_flag_key,
        input_dto=input_dto,
    )
    if Experiment.objects.filter(feature_flag=locked_flag).exists():
        raise ValidationError("The authoritative feature flag is already linked to an experiment.")

    return Experiment.objects.create(
        team=team,
        created_by=user,
        feature_flag=locked_flag,
        name=input_dto.name,
        description=_experiment_description(input_dto),
        type=Experiment.ExperimentType.PRODUCT,
        parameters=None,
        running_time_calculation={},
        excluded_variants=None,
        metrics=metrics,
        metrics_secondary=metrics_secondary,
        secondary_metrics=[],
        stats_config=stats_config,
        exposure_criteria=exposure_criteria,
        holdout=None,
        start_date=None,
        end_date=None,
        filters={},
        primary_metrics_ordered_uuids=[metric["uuid"] for metric in metrics],
        secondary_metrics_ordered_uuids=[metric["uuid"] for metric in metrics_secondary],
        scheduling_config=None,
        only_count_matured_users=only_count_matured_users,
        archived=False,
        deleted=False,
        conclusion=None,
        conclusion_comment=None,
        repository=None,
    )


def _validate_access(*, team: Team, user: User) -> None:
    access = UserAccessControl(user=user, team=team)
    if not access.check_access_level_for_resource("experiment", "editor"):
        raise PermissionDenied("You do not have editor access to experiments.")
    if not access.check_access_level_for_resource("feature_flag", "editor"):
        raise PermissionDenied("You do not have editor access to feature flags.")


def _assert_exact_pulse_draft_flag(
    *,
    feature_flag: FeatureFlag,
    team: Team,
    user: User,
    feature_flag_key: str,
    input_dto: PulseExperimentDraftInput,
) -> None:
    expected = _new_inert_feature_flag_data(feature_flag_key=feature_flag_key, input_dto=input_dto)
    if (
        feature_flag.team_id != team.id
        or feature_flag.key != feature_flag_key
        or feature_flag.name != expected["name"]
        or feature_flag.created_by_id != user.id
        or feature_flag.last_modified_by_id != user.id
        or feature_flag.active is not False
        or feature_flag.archived is not False
        or feature_flag.deleted is not False
        or feature_flag.ensure_experience_continuity is not False
        or feature_flag.filters != expected["filters"]
    ):
        raise ValidationError("The server-owned feature flag key already exists with a different configuration.")


def _validate_input(*, feature_flag_key: str, input_dto: PulseExperimentDraftInput) -> None:
    if not feature_flag_key or len(feature_flag_key) > 400:
        raise ValidationError("The server-owned feature flag key must be between 1 and 400 characters.")
    if not input_dto.name or len(input_dto.name) > MAX_PULSE_EXPERIMENT_NAME_LENGTH:
        raise ValidationError("Experiment name must be between 1 and 400 characters.")
    if not input_dto.hypothesis:
        raise ValidationError("Experiment hypothesis is required.")
    if len(_experiment_description(input_dto)) > MAX_PULSE_EXPERIMENT_DESCRIPTION_LENGTH:
        raise ValidationError("Experiment description and hypothesis must be at most 3000 characters together.")
    if not 2 <= len(input_dto.variants) <= MAX_PULSE_VARIANTS:
        raise ValidationError(f"Experiment drafts need between 2 and {MAX_PULSE_VARIANTS} variants.")
    if len(input_dto.secondary_metrics) > MAX_PULSE_METRICS - 1:
        raise ValidationError(f"Experiment drafts support at most {MAX_PULSE_METRICS} metrics.")
    _validate_variants(input_dto.variants)
    for metric in (input_dto.primary_metric, *input_dto.secondary_metrics):
        _validate_metric_ref(metric)


def _validate_variants(variants: tuple[PulseExperimentVariant, ...]) -> None:
    keys: set[str] = set()
    for variant in variants:
        if not variant.key or len(variant.key) > 100:
            raise ValidationError("Variant keys must be between 1 and 100 characters.")
        if not variant.name or len(variant.name) > 400:
            raise ValidationError("Variant names must be between 1 and 400 characters.")
        if variant.key in keys:
            raise ValidationError("Experiment draft variant keys must be unique.")
        keys.add(variant.key)


def _validate_metric_ref(metric: PulseExperimentMetricRef) -> None:
    if metric.kind == "event":
        if metric.event_name is None or not metric.event_name.strip() or len(metric.event_name) > 400:
            raise ValidationError("Event metric names must be between 1 and 400 characters.")
    elif metric.kind == "action":
        if metric.action_id is None or metric.action_id <= 0:
            raise ValidationError("Action metric IDs must be positive integers.")
    else:
        raise ValidationError("Pulse experiment metrics must reference an event or action.")


def _validate_metric_references(*, team: Team, user: User, input_dto: PulseExperimentDraftInput) -> None:
    service = ExperimentService(team=team, user=user)
    metrics = [_metric_ref_to_metric(input_dto.primary_metric)]
    metrics_secondary = [_metric_ref_to_metric(metric) for metric in input_dto.secondary_metrics]
    service.validate_metric_action_ids(metrics, team.id)
    service.validate_metric_action_ids(metrics_secondary, team.id)
    service.validate_metric_event_names(metrics)
    service.validate_metric_event_names(metrics_secondary)
    enforce_warehouse_metric_access([*metrics, *metrics_secondary], team=team, user=user)


def _metric_ref_to_metric(metric: PulseExperimentMetricRef) -> dict[str, object]:
    if metric.kind == "event":
        return {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "EventsNode", "event": metric.event_name},
        }
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "ActionsNode", "id": metric.action_id},
    }


def _new_inert_feature_flag_data(*, feature_flag_key: str, input_dto: PulseExperimentDraftInput) -> dict[str, object]:
    variant_count = len(input_dto.variants)
    base_percentage, remainder = divmod(100, variant_count)
    variants = [
        {
            "key": variant.key,
            "name": variant.name,
            "rollout_percentage": base_percentage + (1 if index < remainder else 0),
        }
        for index, variant in enumerate(input_dto.variants)
    ]
    return {
        "key": feature_flag_key,
        "name": f"Feature Flag for Experiment {input_dto.name}",
        "active": False,
        "creation_context": "experiments",
        "ensure_experience_continuity": False,
        "filters": {
            "aggregation_group_type_index": None,
            "groups": [{"properties": [], "rollout_percentage": 0, "aggregation_group_type_index": None}],
            "multivariate": {"variants": variants},
        },
    }


def _experiment_description(input_dto: PulseExperimentDraftInput) -> str:
    sections = [f"Hypothesis: {input_dto.hypothesis}"]
    if input_dto.description:
        sections.insert(0, input_dto.description)
    if input_dto.target_description:
        sections.append(f"Target: {input_dto.target_description}")
    return "\n\n".join(sections)
