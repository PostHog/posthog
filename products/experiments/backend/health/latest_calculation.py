import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from posthog.schema import ExperimentStatsBaseValidated

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.context import (
    LatestCalculation,
    MetricCalculationFailure,
    RatioSide,
    ZeroMetric,
    ingestion_proof_events,
    ingestion_records_project,
)
from products.experiments.backend.health.metric_compiles import can_hold_evaluation_rules, without_available_fields
from products.experiments.backend.logic.result_stats import VariantResult, parse_stored_response
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_calculation_configs,
    calculation_metric_name,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_validation import event_last_seen, metric_nodes
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricResult
from products.experiments.backend.recalculation import get_latest_recalculation
from products.experiments.backend.temporal.models import RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE

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
        hours_of_data=(run.query_to - experiment.start_date) / timedelta(hours=1)
        if run.query_to is not None and experiment.start_date is not None
        else None,
    )


@frozen
class _ZeroResult:
    calculation_config: MetricCalculationConfig
    # None when the metric itself reads zero, rather than a side of a ratio.
    ratio_side: RatioSide | None
    stats: tuple[ExperimentStatsBaseValidated | VariantResult, ...]
    # The nodes that the zero reads, without the other side of a ratio.
    nodes: tuple[dict, ...]

    @property
    def events(self) -> tuple[str, ...]:
        names = (node.get("event") for node in self.nodes if node.get("kind") == "EventsNode")
        return tuple(dict.fromkeys(name for name in names if isinstance(name, str) and name.strip()))

    @property
    def warehouse_tables(self) -> tuple[str, ...]:
        names = (node.get("table_name") for node in self.nodes if node.get("kind") == "ExperimentDataWarehouseNode")
        return tuple(dict.fromkeys(name for name in names if isinstance(name, str) and name))


def _zero_metrics(
    experiment: Experiment, completed: list[tuple[MetricCalculationConfig, ExperimentMetricResult]]
) -> tuple[ZeroMetric, ...]:
    zero = [result for config, row in completed for result in _zero_results(config, row)]
    if not zero:
        return ()
    events = {event for result in zero for event in result.events}
    last_seen = event_last_seen(experiment.team.project_id, ingestion_proof_events(events)) if events else {}
    # While ingestion skips the project, `last_seen_at` stays old for an event that still arrives.
    if not ingestion_records_project(last_seen):
        last_seen = {}
    return tuple(_zero_metric(experiment, result, last_seen) for result in zero)


def _zero_results(calculation_config: MetricCalculationConfig, row: ExperimentMetricResult) -> tuple[_ZeroResult, ...]:
    """The metric, or each side of a ratio, that reads zero in every variant of the row."""
    response = parse_stored_response(row.result)
    if response is None or response.baseline is None:
        return ()
    stats = (response.baseline, *(response.variant_results or []))
    definition = calculation_config.definition
    # `sum_squares` tells a metric of zeros from values that cancel out.
    numerator_is_zero = all(stat.sum == 0 and stat.sum_squares == 0 for stat in stats)
    if definition.get("metric_type") != "ratio":
        if not numerator_is_zero:
            return ()
        nodes = tuple(metric_nodes(dict(definition)))
        return (_ZeroResult(calculation_config=calculation_config, ratio_side=None, stats=stats, nodes=nodes),)
    sides: list[RatioSide] = []
    if numerator_is_zero:
        sides.append("numerator")
    if all(_denominator_is_zero(stat) for stat in stats):
        sides.append("denominator")
    return tuple(
        _ZeroResult(
            calculation_config=calculation_config,
            ratio_side=side,
            stats=stats,
            nodes=(node,) if isinstance(node := definition.get(side), dict) else (),
        )
        for side in sides
    )


def _denominator_is_zero(stat: ExperimentStatsBaseValidated | VariantResult) -> bool:
    # A variant without exposures gets zero stats that leave the denominator unset.
    if stat.number_of_samples == 0:
        return True
    return stat.denominator_sum == 0 and not stat.denominator_sum_squares


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
        warehouse_tables=result.warehouse_tables,
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
    its error doesn't show on a metric that has a row. A failed calculation keeps the completed row that held its
    window, so its error doesn't show on a metric whose row is completed.
    """
    error: dict[str, Any] = entry if isinstance(entry, dict) else {}
    rejected = error.get("error_type") == RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE
    if row is not None and (rejected or row.status == ExperimentMetricResult.Status.COMPLETED):
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
