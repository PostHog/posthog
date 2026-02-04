import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Union
from zoneinfo import ZoneInfo

from django.conf import settings

from posthoganalytics import capture_exception
from typing_extensions import TypeIs

from posthog.schema import (
    CacheMissResponse,
    ExperimentExposureQuery,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    MaxExperimentMetricResult,
    MaxExperimentSummaryContext,
    MaxExperimentVariantResultBayesian,
    MaxExperimentVariantResultFrequentist,
    QueryStatusResponse,
)

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.experiments.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Experiment
from posthog.sync import database_sync_to_async


@dataclass
class MetricQueryResult:
    metric_result: MaxExperimentMetricResult | None
    refresh_time: datetime | None
    pending: bool


@dataclass
class ExposureQueryResult:
    exposures: dict[str, float] | None
    refresh_time: datetime | None
    pending: bool


MAX_METRICS_TO_SUMMARIZE = 20
MAX_CONCURRENT_EXPERIMENT_SUMMARY_QUERIES = 10

# This threshold is just to avoid minor discrepancies in timestamps.
# The check itself compares the frontend timestamp with the last
# backend refresh timestamp. So leaving the browser open while not
# having any new data on the backend will not trigger a warning.
FRESHNESS_THRESHOLD_SECONDS = 60

ExperimentMetricType = Union[
    ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric, ExperimentRetentionMetric
]


def parse_metric_dict(metric_dict: dict) -> ExperimentMetricType | None:
    """Parse a metric dictionary into its typed Pydantic object."""
    metric_type = metric_dict.get("metric_type")
    if metric_type == "mean":
        return ExperimentMeanMetric(**metric_dict)
    if metric_type == "funnel":
        return ExperimentFunnelMetric(**metric_dict)
    if metric_type == "ratio":
        return ExperimentRatioMetric(**metric_dict)
    if metric_type == "retention":
        return ExperimentRetentionMetric(**metric_dict)
    return None


def get_delta_from_interval(interval: list[float] | None) -> float | None:
    """Calculate delta as the midpoint of a credible/confidence interval."""
    if interval and len(interval) >= 2:
        return (interval[0] + interval[1]) / 2
    return None


def get_chance_to_win(chance_to_win: float | None, goal: str | None) -> float | None:
    """
    Get chance to win adjusted for the metric goal.
    When goal is 'decrease', invert chance to win because lower values are better.
    """
    if chance_to_win is None:
        return None
    # When goal is to decrease, invert chance to win because lower values are better
    if goal == "decrease":
        return 1 - chance_to_win
    return chance_to_win


def transform_variant_for_max(
    variant: ExperimentVariantResultBayesian | ExperimentVariantResultFrequentist,
    stats_method: str,
    goal: str | None = None,
) -> MaxExperimentVariantResultBayesian | MaxExperimentVariantResultFrequentist:
    """Transform a variant result to the Max AI format."""
    if stats_method == "bayesian" and isinstance(variant, ExperimentVariantResultBayesian):
        return MaxExperimentVariantResultBayesian(
            key=variant.key,
            chance_to_win=get_chance_to_win(variant.chance_to_win, goal),
            credible_interval=variant.credible_interval,
            delta=get_delta_from_interval(variant.credible_interval),
            significant=variant.significant or False,
        )
    if isinstance(variant, ExperimentVariantResultFrequentist):
        return MaxExperimentVariantResultFrequentist(
            key=variant.key,
            p_value=variant.p_value,
            confidence_interval=variant.confidence_interval,
            delta=get_delta_from_interval(variant.confidence_interval),
            significant=variant.significant or False,
        )
    return MaxExperimentVariantResultBayesian(
        key=variant.key,
        chance_to_win=None,
        credible_interval=None,
        delta=None,
        significant=False,
    )


def get_default_metric_title(metric_dict: dict) -> str:
    """Generate a default title for a metric based on its configuration."""
    metric_type = metric_dict.get("metric_type", "")
    if metric_type == "funnel":
        series = metric_dict.get("series", [])
        if series:
            first_event = series[0].get("event") or series[0].get("name") or "Event"
            last_event = series[-1].get("event") or series[-1].get("name") or "Event"
            if len(series) == 1:
                return f"{first_event} conversion"
            return f"{first_event} to {last_event}"
    elif metric_type == "mean":
        source = metric_dict.get("source", {})
        event = source.get("event") or source.get("name") or "Event"
        return f"Mean {event}"
    elif metric_type == "ratio":
        return "Ratio metric"
    elif metric_type == "retention":
        return "Retention metric"
    return "Metric"


def is_incomplete_response(result: Any) -> TypeIs[CacheMissResponse | QueryStatusResponse]:
    """Check if result is a cache miss or pending query status (i.e. incomplete result)."""
    return isinstance(result, (CacheMissResponse, QueryStatusResponse))


class ExperimentSummaryDataService:
    def __init__(self, team):
        self._team = team

    async def fetch_experiment_data(
        self, experiment_id: int
    ) -> tuple[MaxExperimentSummaryContext, datetime | None, bool]:
        """
        Fetch experiment data from the database and run cached queries concurrently.
        Returns the context data, the last refresh timestamp, and whether any calculation is pending.
        """
        team_id = self._team.id

        # First, fetch the experiment (required to build queries)
        @database_sync_to_async(thread_sensitive=settings.TEST)
        def fetch_experiment():
            return Experiment.objects.select_related("feature_flag", "holdout", "team").get(
                id=experiment_id, team_id=team_id, deleted=False
            )

        try:
            experiment = await fetch_experiment()
        except Experiment.DoesNotExist:
            raise ValueError(f"Experiment {experiment_id} not found or access denied")

        if not experiment.start_date:
            raise ValueError(f"Experiment {experiment_id} has not been started yet")

        feature_flag = experiment.feature_flag
        if not feature_flag:
            raise ValueError(f"Experiment {experiment_id} has no feature flag")

        multivariate = feature_flag.filters.get("multivariate", {})
        variants = [v.get("key") for v in multivariate.get("variants", []) if v.get("key")]
        stats_method = get_experiment_stats_method(experiment)

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXPERIMENT_SUMMARY_QUERIES)

        # Create coroutines for all queries to run concurrently
        async def run_metric_query_async(metric_dict: dict, metric_index: int) -> MetricQueryResult:
            @database_sync_to_async(thread_sensitive=settings.TEST)
            def _run_query():
                metric_obj = parse_metric_dict(metric_dict)
                if not metric_obj:
                    return MetricQueryResult(metric_result=None, refresh_time=None, pending=False)

                experiment_query = ExperimentQuery(
                    experiment_id=experiment_id,
                    metric=metric_obj,
                )
                query_runner = ExperimentQueryRunner(
                    query=experiment_query,
                    team=experiment.team,
                    workload=Workload.ONLINE,
                )
                result = query_runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)
                refresh_time = getattr(result, "last_refresh", None)

                if is_incomplete_response(result):
                    return MetricQueryResult(metric_result=None, refresh_time=None, pending=True)

                if not result.variant_results:
                    return MetricQueryResult(metric_result=None, refresh_time=refresh_time, pending=False)

                metric_goal = metric_dict.get("goal")
                transformed_variants = [
                    transform_variant_for_max(v, stats_method, metric_goal) for v in result.variant_results
                ]
                metric_name = metric_dict.get("name") or get_default_metric_title(metric_dict)

                return MetricQueryResult(
                    metric_result=MaxExperimentMetricResult(
                        name=f"{metric_index + 1}. {metric_name}",
                        goal=metric_dict.get("goal"),
                        variant_results=transformed_variants,
                    ),
                    refresh_time=refresh_time,
                    pending=False,
                )

            async with semaphore:
                return await _run_query()

        async def run_exposure_query_async() -> ExposureQueryResult:
            @database_sync_to_async(thread_sensitive=settings.TEST)
            def _run_query():
                try:
                    exposure_query = ExperimentExposureQuery(
                        experiment_id=experiment_id,
                        experiment_name=experiment.name,
                        feature_flag=feature_flag.filters,
                        start_date=experiment.start_date.isoformat() if experiment.start_date else None,
                        end_date=experiment.end_date.isoformat() if experiment.end_date else None,
                        exposure_criteria=experiment.exposure_criteria,
                        holdout=experiment.holdout,
                    )
                    exposure_runner = ExperimentExposuresQueryRunner(
                        query=exposure_query,
                        team=experiment.team,
                    )
                    exposure_result = exposure_runner.run(
                        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
                    )

                    if is_incomplete_response(exposure_result):
                        return ExposureQueryResult(exposures=None, refresh_time=None, pending=True)

                    exposures = None
                    if exposure_result and exposure_result.total_exposures:
                        exposures = {k: float(v) for k, v in exposure_result.total_exposures.items()}

                    refresh_time = getattr(exposure_result, "last_refresh", None) if exposure_result else None
                    return ExposureQueryResult(exposures=exposures, refresh_time=refresh_time, pending=False)
                except Exception as e:
                    capture_exception(e, properties={"experiment_id": experiment_id})
                    return ExposureQueryResult(exposures=None, refresh_time=None, pending=False)

            async with semaphore:
                return await _run_query()

        # Build list of all query tasks
        primary_metrics = experiment.metrics or []
        secondary_metrics = experiment.metrics_secondary or []

        primary_metric_tasks = [
            run_metric_query_async(metric, i) for i, metric in enumerate(primary_metrics[:MAX_METRICS_TO_SUMMARIZE])
        ]
        secondary_metric_tasks = [
            run_metric_query_async(metric, i) for i, metric in enumerate(secondary_metrics[:MAX_METRICS_TO_SUMMARIZE])
        ]
        exposure_task = run_exposure_query_async()

        # Run all queries concurrently using asyncio.gather.
        # This waits for all results (not streaming), which is appropriate here
        # since we need all metric results to build a complete summary response.
        all_results = await asyncio.gather(
            *primary_metric_tasks,
            *secondary_metric_tasks,
            exposure_task,
            return_exceptions=True,  # Don't fail on individual query errors
        )

        # Split results back into categories
        primary_count = len(primary_metric_tasks)
        secondary_count = len(secondary_metric_tasks)

        primary_query_results: list[MetricQueryResult | BaseException] = all_results[:primary_count]  # type: ignore[assignment]
        secondary_query_results: list[MetricQueryResult | BaseException] = all_results[
            primary_count : primary_count + secondary_count
        ]  # type: ignore[assignment]
        exposure_query_result = all_results[-1]

        # Aggregate results
        latest_refresh: datetime | None = None
        pending_calculation = False

        def process_metric_results(
            query_results: list[MetricQueryResult | BaseException],
        ) -> list[MaxExperimentMetricResult]:
            nonlocal latest_refresh, pending_calculation
            results: list[MaxExperimentMetricResult] = []
            for qr in query_results:
                if isinstance(qr, BaseException):
                    capture_exception(qr, properties={"experiment_id": experiment_id})
                    continue
                if qr.pending:
                    pending_calculation = True
                if qr.metric_result:
                    results.append(qr.metric_result)
                if qr.refresh_time and (latest_refresh is None or qr.refresh_time > latest_refresh):
                    latest_refresh = qr.refresh_time
            return results

        primary_results = process_metric_results(primary_query_results)
        secondary_results = process_metric_results(secondary_query_results)

        # Process exposure result
        exposures: dict[str, float] | None = None
        if isinstance(exposure_query_result, BaseException):
            capture_exception(exposure_query_result, properties={"experiment_id": experiment_id})
        elif isinstance(exposure_query_result, ExposureQueryResult):
            if exposure_query_result.pending:
                pending_calculation = True
            exposures = exposure_query_result.exposures
            if exposure_query_result.refresh_time and (
                latest_refresh is None or exposure_query_result.refresh_time > latest_refresh
            ):
                latest_refresh = exposure_query_result.refresh_time

        return (
            MaxExperimentSummaryContext(
                experiment_id=experiment_id,
                experiment_name=experiment.name or "Unnamed experiment",
                description=experiment.description or None,
                exposures=exposures,
                variants=variants,
                primary_metrics_results=primary_results,
                secondary_metrics_results=secondary_results,
                stats_method=stats_method,
            ),
            latest_refresh,
            pending_calculation,
        )

    def check_data_freshness(
        self, frontend_last_refresh: str | None, backend_last_refresh: datetime | None
    ) -> str | None:
        """
        Check if there's a significant difference between frontend and backend data freshness.
        Returns a warning message if data might have changed, None otherwise.
        """
        if not frontend_last_refresh or not backend_last_refresh:
            return None

        try:
            frontend_time = datetime.fromisoformat(frontend_last_refresh.replace("Z", "+00:00"))
            if frontend_time.tzinfo is None:
                frontend_time = frontend_time.replace(tzinfo=ZoneInfo("UTC"))
            if backend_last_refresh.tzinfo is None:
                backend_last_refresh = backend_last_refresh.replace(tzinfo=ZoneInfo("UTC"))

            time_diff = abs((backend_last_refresh - frontend_time).total_seconds())
            if time_diff > FRESHNESS_THRESHOLD_SECONDS:
                return (
                    f"**Note:** The experiment data has been updated since you loaded this page "
                    f"(approximately {int(time_diff / 60)} minutes ago). "
                    f"The summary below reflects the most current data."
                )
        except (ValueError, TypeError):
            pass

        return None
