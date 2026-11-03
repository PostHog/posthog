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


def load_primary_metric_windows(experiment: Experiment) -> tuple[MetricWindow, ...] | None:
    """
    The windows of the primary metrics of a launched experiment that hasn't ended, isn't archived and has
    `only_count_matured_users` on, or None. Never raises: the check that reads them then reports that it couldn't check.
    """
    start_date = experiment.start_date
    if start_date is None or experiment.is_stopped or experiment.archived or not experiment.only_count_matured_users:
        return None
    try:
        return _load_primary_metric_windows(experiment, start_date)
    except Exception as error:
        capture_exception(error)
        return None


def metric_window(*, name: str, definition: dict[str, Any], start_date: datetime) -> MetricWindow | None:
    """The window of one metric definition. None when the definition doesn't parse, which `metric_cannot_compile`
    reports, so this captures nothing."""
    try:
        window_seconds = get_maturity_window_seconds(build_metric(definition))
    except ValidationError:
        return None
    return MetricWindow(
        name=name,
        window_seconds=window_seconds,
        first_users_count_at=start_date + timedelta(seconds=window_seconds),
    )


def _load_primary_metric_windows(experiment: Experiment, start_date: datetime) -> tuple[MetricWindow, ...] | None:
    # Metrics that share a uuid share its first definition, so one window covers them.
    configs: dict[str, MetricCalculationConfig] = {}
    for calculation_config in build_primary_calculation_configs(experiment):
        configs.setdefault(calculation_config.metric_id, calculation_config)
    windows: list[MetricWindow] = []
    for calculation_config in configs.values():
        window = metric_window(
            name=calculation_metric_name(experiment, calculation_config),
            definition=calculation_config.definition,
            start_date=start_date,
        )
        if window is None:
            return None
        windows.append(window)
    return tuple(windows)
