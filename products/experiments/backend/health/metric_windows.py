from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from posthog.exceptions_capture import capture_exception

from products.experiments.backend.health.context import MetricWindow
from products.experiments.backend.hogql_queries.experiment_metric_values import get_maturity_window_seconds
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_primary_calculation_configs,
    calculation_metric_name,
)
from products.experiments.backend.metric_resolution import build_metric
from products.experiments.backend.models.experiment import Experiment


def has_metric_windows(experiment: Experiment) -> bool:
    return not experiment.archived and experiment.only_count_matured_users


def load_primary_metric_windows(
    experiment: Experiment, *, launched_at: datetime | None
) -> tuple[MetricWindow, ...] | None:
    """
    The windows of the primary metrics of an experiment that launched, or launches, at `launched_at`, isn't archived
    and has `only_count_matured_users` on, or None. Never raises: the check that reads them then reports that it
    couldn't check.
    """
    if launched_at is None or not has_metric_windows(experiment):
        return None
    try:
        return _load_primary_metric_windows(experiment, launched_at)
    except Exception as error:
        capture_exception(error)
        return None


def metric_window(*, name: str, definition: dict[str, Any], launched_at: datetime) -> MetricWindow | None:
    """The window of one metric definition. None when the definition doesn't parse, which `metric_cannot_compile`
    reports, so this captures nothing."""
    try:
        window_seconds = get_maturity_window_seconds(build_metric(definition))
    except ValidationError:
        return None
    return MetricWindow(
        name=name,
        window_seconds=window_seconds,
        first_users_count_at=launched_at + timedelta(seconds=window_seconds),
    )


def _load_primary_metric_windows(experiment: Experiment, launched_at: datetime) -> tuple[MetricWindow, ...] | None:
    # Metrics that share a uuid share its first definition, so one window covers them.
    configs: dict[str, MetricCalculationConfig] = {}
    for calculation_config in build_primary_calculation_configs(experiment):
        configs.setdefault(calculation_config.metric_id, calculation_config)
    windows: list[MetricWindow] = []
    for calculation_config in configs.values():
        window = metric_window(
            name=calculation_metric_name(experiment, calculation_config),
            definition=calculation_config.definition,
            launched_at=launched_at,
        )
        if window is None:
            return None
        windows.append(window)
    return tuple(windows)
