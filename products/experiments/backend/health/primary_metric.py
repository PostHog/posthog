from collections.abc import Mapping
from typing import Any

from posthog.exceptions_capture import capture_exception

from products.experiments.backend.health.context import PrimaryMetric, StoredMetricResult, StoredVariantResult
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_primary_calculation_configs,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore, ResultSummary
from products.experiments.backend.metric_resolution import saved_metric_links
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.setup_context import PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT


def load_primary_metric(experiment: Experiment) -> PrimaryMetric | None:
    """
    The first primary metric of a launched experiment with its current stored result, or None. Never raises: the
    checks that read it then report that they couldn't check.
    """
    if not experiment.is_launched:
        return None
    try:
        return _load_primary_metric(experiment)
    except Exception as error:
        capture_exception(error)
        return None


def _load_primary_metric(experiment: Experiment) -> PrimaryMetric | None:
    team_config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    calculation_config = next(iter(build_primary_calculation_configs(experiment, team_config=team_config)), None)
    if calculation_config is None:
        return None
    is_funnel = calculation_config.definition.get("metric_type") == "funnel"
    summary = MetricResultStore(experiment_id=experiment.id).current_outcome(calculation_config) if is_funnel else None
    return PrimaryMetric(
        name=_metric_name(experiment, calculation_config),
        is_funnel=is_funnel,
        minimum_detectable_effect=_minimum_detectable_effect(experiment, team_config),
        result=_stored_result(summary) if summary is not None else None,
    )


def _metric_name(experiment: Experiment, calculation_config: MetricCalculationConfig) -> str:
    definition = calculation_config.definition
    # An inline metric wins over a saved metric with the same uuid, as in `get_metrics_for_calculation`.
    inline_uuids = {metric.get("uuid") for metric in experiment.metrics or [] if isinstance(metric, dict)}
    if calculation_config.metric_id not in inline_uuids:
        for link in saved_metric_links(experiment):
            query = link.saved_metric.query
            if isinstance(query, dict) and query.get("uuid") == calculation_config.metric_id:
                return link.saved_metric.name
    return definition.get("name") or get_default_metric_title(definition)


def _minimum_detectable_effect(experiment: Experiment, team_config: TeamExperimentsConfig) -> float:
    running_time_calculation = experiment.running_time_calculation
    planned = (
        running_time_calculation.get("minimum_detectable_effect")
        if isinstance(running_time_calculation, dict)
        else None
    )
    if isinstance(planned, int | float) and not isinstance(planned, bool) and planned > 0:
        return float(planned)
    return float(team_config.default_minimum_detectable_effect or PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT)


def _stored_result(summary: ResultSummary) -> StoredMetricResult | None:
    baseline_samples = _number(summary.baseline_samples)
    baseline_sum = _number(summary.baseline_sum)
    if baseline_samples is None or baseline_sum is None:
        return None
    return StoredMetricResult(
        baseline_samples=int(baseline_samples),
        baseline_sum=baseline_sum,
        variants=tuple(
            variant for variant in (_stored_variant(row) for row in summary.variant_results) if variant is not None
        ),
    )


def _stored_variant(row: Mapping[str, Any]) -> StoredVariantResult | None:
    key = row.get("key")
    samples = _number(row.get("number_of_samples"))
    total = _number(row.get("sum"))
    if not isinstance(key, str) or samples is None or total is None:
        return None
    significant = row.get("significant")
    return StoredVariantResult(
        key=key,
        samples=int(samples),
        sum=total,
        significant=significant if isinstance(significant, bool) else None,
    )


def _number(value: object) -> float | None:
    # `ResultSummary` carries the baseline's stored JSON values as text, and the variants' as parsed JSON.
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
