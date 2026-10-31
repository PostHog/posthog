import re
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from posthog.schema import (
    ExperimentStatsBaseValidated,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
)

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.event_definitions.backend.models import EventDefinition, effective_project_id_expr
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.context import (
    LatestCalculation,
    MetricCalculationFailure,
    RatioSide,
    ZeroMetric,
)
from products.experiments.backend.health.metric_compiles import can_hold_evaluation_rules, without_available_fields
from products.experiments.backend.logic.result_stats import parse_stored_response
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_calculation_configs,
    calculation_metric_name,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_validation import metric_nodes
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricResult
from products.experiments.backend.recalculation import get_latest_recalculation
from products.experiments.backend.temporal.models import RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE

ExperimentVariantResult = ExperimentVariantResultBayesian | ExperimentVariantResultFrequentist

# The calculation doesn't apply the reader's warehouse access, so the names that HogQL suggests in its message can name
# a table or a column that the reader may not query.
_SUGGESTED_NAMES = re.compile(r" Did you mean: [^?]*\?")


def load_latest_calculation(experiment: Experiment) -> LatestCalculation | None:
    """The latest finished calculation of the metrics of a launched experiment that isn't archived, or None. Never
    raises: the check that reads it then reports that it couldn't check."""
    if not experiment.is_launched or experiment.archived:
        return None
    try:
        return _load_latest_calculation(experiment)
    except Exception as error:
        capture_exception(error)
        return None


def _load_latest_calculation(experiment: Experiment) -> LatestCalculation:
    team_config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    # Metrics that share a uuid share one result and one error on the page.
    configs: dict[str, MetricCalculationConfig] = {}
    for calculation_config in build_calculation_configs(experiment, team_config=team_config):
        configs.setdefault(calculation_config.metric_id, calculation_config)
    # The results page shows the latest run that finished. Without one it shows the daily points, which hold no
    # failures, or else the run in progress, whose errors can still change, so the check waits for a finished run.
    run = get_latest_recalculation(experiment)
    if run is None:
        return LatestCalculation(
            metric_count=len(configs),
            finished_at=None,
            failures=(),
            completed_count=0,
            completed_exposures_paths=frozenset(),
        )
    metric_errors = run.metric_errors if isinstance(run.metric_errors, dict) else {}
    results = MetricResultStore(experiment_id=experiment.id)
    rows = {row.metric_uuid: row for row in results.for_run(run, with_result=False)}
    failures = tuple(
        failure
        for metric_id, calculation_config in configs.items()
        if (
            failure := _shown_failure(experiment, calculation_config, metric_errors.get(metric_id), rows.get(metric_id))
        )
        is not None
    )
    failed = {failure.metric_id for failure in failures}
    completed = [
        row
        for metric_id in configs
        if metric_id not in failed
        and (row := rows.get(metric_id)) is not None
        and row.status == ExperimentMetricResult.Status.COMPLETED
    ]
    return LatestCalculation(
        metric_count=len(configs),
        finished_at=run.completed_at,
        failures=failures,
        completed_count=len(completed),
        completed_exposures_paths=results.exposures_paths(completed) if failures else frozenset(),
        zero_metrics=_zero_metrics(
            experiment, [(configs[row.metric_uuid], row) for row in results.with_zero_baseline(completed)]
        ),
        hours_of_data=(run.query_to - experiment.start_date).total_seconds() / 3600
        if run.query_to is not None and experiment.start_date is not None
        else None,
    )


@frozen
class _ZeroResult:
    calculation_config: MetricCalculationConfig
    # None when the metric itself reads zero, rather than a side of a ratio.
    ratio_side: RatioSide | None
    stats: tuple[ExperimentStatsBaseValidated | ExperimentVariantResult, ...]
    # The nodes that the zero reads, without the other side of a ratio.
    nodes: tuple[dict, ...]

    @property
    def events(self) -> tuple[str, ...]:
        names = (node.get("event") for node in self.nodes if node.get("kind") == "EventsNode")
        return tuple(dict.fromkeys(name for name in names if isinstance(name, str) and name.strip()))


def _zero_metrics(
    experiment: Experiment, completed: list[tuple[MetricCalculationConfig, ExperimentMetricResult]]
) -> tuple[ZeroMetric, ...]:
    zero = [result for config, row in completed if (result := _zero_result(config, row)) is not None]
    if not zero:
        return ()
    last_seen = _event_last_seen(experiment.team.project_id, {event for result in zero for event in result.events})
    return tuple(_zero_metric(experiment, result, last_seen) for result in zero)


def _zero_result(calculation_config: MetricCalculationConfig, row: ExperimentMetricResult) -> _ZeroResult | None:
    response = parse_stored_response(row.result)
    if response is None or response.baseline is None:
        return None
    stats = (response.baseline, *(response.variant_results or []))
    definition = calculation_config.definition
    # `sum_squares` tells a metric of zeros from values that cancel out.
    numerator_is_zero = all(stat.sum == 0 and stat.sum_squares == 0 for stat in stats)
    if definition.get("metric_type") != "ratio":
        if not numerator_is_zero:
            return None
        return _ZeroResult(
            calculation_config=calculation_config,
            ratio_side=None,
            stats=stats,
            nodes=tuple(metric_nodes(dict(definition))),
        )
    if numerator_is_zero:
        side: RatioSide = "numerator"
    elif all(stat.denominator_sum == 0 and not stat.denominator_sum_squares for stat in stats):
        side = "denominator"
    else:
        return None
    node = definition.get(side)
    return _ZeroResult(
        calculation_config=calculation_config,
        ratio_side=side,
        stats=stats,
        nodes=(node,) if isinstance(node, dict) else (),
    )


def _event_last_seen(project_id: int, names: Collection[str]) -> dict[str, datetime]:
    definitions = EventDefinition.objects.alias(effective_project_id=effective_project_id_expr()).filter(
        effective_project_id=project_id, name__in=names
    )
    return {name: seen for name, seen in definitions.values_list("name", "last_seen_at") if seen is not None}


def _zero_metric(experiment: Experiment, result: _ZeroResult, last_seen: Mapping[str, datetime]) -> ZeroMetric:
    calculation_config = result.calculation_config
    start_date = experiment.start_date
    return ZeroMetric(
        metric_id=calculation_config.metric_id,
        name=calculation_metric_name(experiment, calculation_config),
        role=calculation_config.role,
        exposures=sum(stat.number_of_samples for stat in result.stats),
        ratio_side=result.ratio_side,
        definition=calculation_config.definition,
        # `step_counts` holds the entities that reached each step of the metric, so its first count is the largest.
        reached_earlier_step=sum(stat.step_counts[0] for stat in result.stats if stat.step_counts),
        events=result.events,
        has_blank_event=any(
            node.get("kind") == "EventsNode" and node.get("event") is not None and not str(node["event"]).strip()
            for node in result.nodes
        ),
        has_filters=any(node.get("properties") for node in result.nodes),
        stopped_events={
            event: seen
            for event in result.events
            if (seen := last_seen.get(event)) is not None and start_date is not None and seen < start_date
        },
    )


def _shown_failure(
    experiment: Experiment,
    calculation_config: MetricCalculationConfig,
    entry: object,
    row: ExperimentMetricResult | None,
) -> MetricCalculationFailure | None:
    """The failure that the results page shows for one metric, or None.

    pinned: `resolveErrorByUuid` in experimentMetricsLogic.ts. The run's error entry wins over a failed row,
    because it also covers failures before the query ran. A rejected run carries the rows of the run before it, so
    its error doesn't show on a metric that has a row.
    """
    error: dict[str, Any] = entry if isinstance(entry, dict) else {}
    if error.get("error_type") == RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE and row is not None:
        error = {}
    message = error.get("message")
    if not isinstance(message, str):
        message = row.error_message if row is not None and row.status == ExperimentMetricResult.Status.FAILED else None
    if not message:
        return None
    error_type = error.get("error_type")
    step = error.get("step")
    exposures_path = error.get("exposures_path")
    return MetricCalculationFailure(
        metric_id=calculation_config.metric_id,
        name=calculation_metric_name(experiment, calculation_config),
        role=calculation_config.role,
        error_type=error_type if isinstance(error_type, str) else None,
        step=step if isinstance(step, str) else None,
        message=_SUGGESTED_NAMES.sub("", without_available_fields(message)),
        can_quote_evaluation_rules=can_hold_evaluation_rules(calculation_config.definition),
        retriable=error.get("retriable") is True,
        definition=calculation_config.definition,
        exposures_path=ExposuresPath(exposures_path)
        if isinstance(exposures_path, str) and exposures_path in ExposuresPath
        else None,
    )
