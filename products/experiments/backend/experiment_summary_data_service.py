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

MAX_METRICS_TO_SUMMARIZE = 20
FRESHNESS_THRESHOLD_MINUTES = 30

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
        Fetch experiment data from the database and run cached queries.
        Returns the context data and the last refresh timestamp.
        """
        team_id = self._team.id

        @database_sync_to_async(thread_sensitive=settings.TEST)
        def fetch_data() -> tuple[MaxExperimentSummaryContext, datetime | None, bool]:
            experiment = Experiment.objects.select_related("feature_flag", "holdout", "team").get(
                id=experiment_id, team_id=team_id, deleted=False
            )

            if not experiment.start_date:
                raise ValueError(f"Experiment {experiment_id} has not been started yet")

            feature_flag = experiment.feature_flag
            if not feature_flag:
                raise ValueError(f"Experiment {experiment_id} has no feature flag")

            multivariate = feature_flag.filters.get("multivariate", {})
            variants = [v.get("key") for v in multivariate.get("variants", []) if v.get("key")]
            stats_method = get_experiment_stats_method(experiment)
            latest_refresh: datetime | None = None
            pending_calculation = False

            def run_metric_query(
                metric_dict: dict, metric_index: int
            ) -> tuple[MaxExperimentMetricResult | None, datetime | None]:
                metric_obj = parse_metric_dict(metric_dict)
                if not metric_obj:
                    return None, None

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
                    nonlocal pending_calculation
                    pending_calculation = True
                    return None, None

                if not result.variant_results:
                    return None, refresh_time

                metric_goal = metric_dict.get("goal")
                transformed_variants = [
                    transform_variant_for_max(v, stats_method, metric_goal) for v in result.variant_results
                ]
                metric_name = metric_dict.get("name") or get_default_metric_title(metric_dict)

                return MaxExperimentMetricResult(
                    name=metric_name,
                    goal=metric_dict.get("goal"),
                    variant_results=transformed_variants,
                ), refresh_time

            def process_metrics(metrics: list[dict], is_primary: bool) -> list[MaxExperimentMetricResult]:
                nonlocal latest_refresh
                results: list[MaxExperimentMetricResult] = []
                for i, metric_dict in enumerate(metrics[:MAX_METRICS_TO_SUMMARIZE]):
                    result, refresh_time = run_metric_query(metric_dict, i)
                    if result:
                        result.name = f"{i + 1}. {result.name}"
                        results.append(result)
                    if refresh_time and (latest_refresh is None or refresh_time > latest_refresh):
                        latest_refresh = refresh_time
                return results

            primary_results = process_metrics(experiment.metrics or [], is_primary=True)
            secondary_results = process_metrics(experiment.metrics_secondary or [], is_primary=False)

            exposures: dict[str, float] | None = None
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
                    pending_calculation = True
                    exposure_result = None

                if exposure_result and exposure_result.total_exposures:
                    exposures = {k: float(v) for k, v in exposure_result.total_exposures.items()}

                if exposure_result:
                    exposure_refresh = getattr(exposure_result, "last_refresh", None)
                    if exposure_refresh and (latest_refresh is None or exposure_refresh > latest_refresh):
                        latest_refresh = exposure_refresh
            except Exception as e:
                capture_exception(e, properties={"experiment_id": experiment_id})

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

        try:
            return await fetch_data()
        except Experiment.DoesNotExist:
            raise ValueError(f"Experiment {experiment_id} not found or access denied")

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
            if time_diff > FRESHNESS_THRESHOLD_MINUTES * 60:
                return (
                    f"**Note:** The experiment data has been updated since you loaded this page "
                    f"(approximately {int(time_diff / 60)} minutes ago). "
                    f"The summary below reflects the most current data."
                )
        except (ValueError, TypeError):
            pass

        return None
