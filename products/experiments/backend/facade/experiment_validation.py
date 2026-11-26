"""Input checks that the experiments API runs before it hands the input to a write.

A check that fails raises the `ValidationError` of Django REST framework, with the message that the API returns.
"""

from datetime import datetime

from pydantic import JsonValue

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import ExperimentHoldout


def holdout_exists(*, team_id: int, holdout_id: int) -> bool:
    """Whether the project of the team has a holdout with the id. Holdouts belong to a project, not to one of its
    environments."""
    return ExperimentHoldout.objects.filter(team_id=team_id, pk=holdout_id).exists()


def validate_date_range(*, start_date: datetime | None, end_date: datetime | None) -> None:
    ExperimentService.validate_experiment_date_range(start_date, end_date)


def validate_saved_metrics_ids(saved_metrics_ids: list[JsonValue] | None, *, team_id: int) -> None:
    ExperimentService.validate_saved_metrics_ids(saved_metrics_ids, team_id)


def validate_running_time_calculation(running_time_calculation: dict[str, JsonValue] | None) -> None:
    ExperimentService.validate_running_time_calculation(running_time_calculation)


def validate_excluded_variants(excluded_variants: list[str] | None) -> None:
    ExperimentService.validate_excluded_variants(excluded_variants)


def validate_exposure_criteria(exposure_criteria: JsonValue) -> None:
    ExperimentService.validate_experiment_exposure_criteria(exposure_criteria)


def validate_metrics(metrics: list[JsonValue] | None) -> None:
    ExperimentService.validate_experiment_metrics(metrics)


def strip_feature_flag_config(parameters: dict[str, JsonValue] | None) -> dict[str, JsonValue] | None:
    """`parameters` without the keys of `FEATURE_FLAG_CONFIG_KEYS`, which the experiment does not store."""
    return ExperimentService.strip_feature_flag_config(parameters)


def feature_flag_config_from_parameters(parameters: dict[str, JsonValue]) -> dict[str, JsonValue] | None:
    """The flag config that the deprecated flag config keys of `parameters` describe, in the flag's own write shape
    (`{filters, ensure_experience_continuity}`), or None when `parameters` has none of those keys."""
    return ExperimentService.feature_flag_config_from_parameters(parameters)
