from concurrent.futures import ThreadPoolExecutor
from typing import Any

from django.db import connection
from django.db.models import QuerySet

import structlog

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.config import BriefSettings
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.sources.strategy import MovementScoringStrategy

logger = structlog.get_logger(__name__)

# A single stuck insight query can't hang the shared synthesize activity: cap each execution so
# the LLM call after it keeps its slice of the 5-min budget. Shared by goal and accountability reads.
_INSIGHT_TIMEOUT_SECONDS = 20


def calculate_insight_results(insight: Insight, team: Team) -> list[Any]:
    """Insight execution shared by gathering, goal, and accountability re-scoring — one execution
    mode so a brief and its later then-vs-now checks read the metric the same way."""
    calculation = calculate_for_query_based_insight(
        insight,
        team=team,
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user=None,
    )
    return calculation.result if isinstance(calculation.result, list) else []


def _run_and_close_connection(insight: Insight, team: Team) -> list[Any]:
    # Runs in a spawned worker thread that Django won't tear down for us, so close the
    # thread-local DB connection ourselves — otherwise a timed-out query strands its connection.
    try:
        return calculate_insight_results(insight, team)
    finally:
        connection.close()


def _execute_within_timeout(insight: Insight, team: Team) -> list[Any]:
    """Run a blocking insight execution with a hard wall-clock cap.

    ThreadPoolExecutor, not asyncio: the collectors run sync inside a worker thread, so there is
    no event loop to wait_for on. A timed-out query keeps running in the background — we stop
    waiting for it and let the read degrade (shutdown(wait=False) so the hung query never blocks).
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_run_and_close_connection, insight, team)
    try:
        return future.result(timeout=_INSIGHT_TIMEOUT_SECONDS)
    finally:
        executor.shutdown(wait=False)


class InsightResultsCache:
    """Memoizes insight executions per short_id and counts every attempt (success or raise).

    Memoization bounds the happy path at one cached-execution-mode run per distinct insight
    (so parallelizing the calls is not worth the machinery); the attempt count lets callers
    budget the failure path too, keeping re-scoring latency bounded inside the synthesize
    activity's shared 5-minute timeout. One instance is shared across the collectors of a
    single brief run so an insight referenced twice executes once. Each execution is wrapped
    in the per-insight wall-clock cap so a stuck query can't hang the shared activity.
    """

    def __init__(self, team: Team) -> None:
        self._team = team
        self._results: dict[str, list[Any]] = {}
        self.attempts = 0

    def results_for(self, insight: Insight) -> list[Any]:
        if insight.short_id not in self._results:
            # A raising execution is deliberately not cached: the caller's per-read handler
            # logs it, and a retry on a later read still counts against the attempt budget.
            self.attempts += 1
            self._results[insight.short_id] = _execute_within_timeout(insight, self._team)
        return self._results[insight.short_id]


def live_insights(team: Team) -> QuerySet[Insight]:
    """The team's non-deleted insights — the only population metric refs may resolve against."""
    return Insight.objects.filter(team=team, deleted=False)


def resolve_metric_insight(team: Team, short_id: str) -> Insight | None:
    """Resolve one metric-ref short_id; lowest id wins when a short_id has duplicates."""
    return live_insights(team).filter(short_id=short_id).order_by("id").first()


def resolve_metric_insights(team: Team, short_ids: set[str]) -> dict[str, Insight]:
    """Batch shape of resolve_metric_insight — same lowest-id-wins rule, one query."""
    insights: dict[str, Insight] = {}
    for insight in live_insights(team).filter(short_id__in=short_ids).order_by("id"):
        insights.setdefault(insight.short_id, insight)
    return insights


def series_daily_values(series_result: Any, period_days: int) -> list[float] | None:
    """Shape-check one calculation series and return its trailing 2×period_days daily values.

    None means a non-trends result shape. Slices before float conversion so an insight with a
    long history doesn't pay for converting the whole series.
    """
    if not isinstance(series_result, dict) or "data" not in series_result:
        return None
    return [float(v) for v in series_result["data"][-2 * period_days :]]


def split_score_windows(values: list[float]) -> tuple[list[float], list[float]] | None:
    """Split a pre-trimmed daily series into (baseline, current) halves.

    Shared by gathering, goal, and accountability re-scoring so "current" always means the same
    window math the movement was originally scored with. Callers trim the series to 2×period_days
    via series_daily_values before calling this. Returns None when there is too little data.
    """
    if len(values) % 2:
        values = values[1:]  # drop the oldest sample so the two windows compare equal lengths
    if len(values) < 2:
        return None
    half = len(values) // 2
    return values[:half], values[half:]


class AnchoredInsightsSource:
    """Gathers movements from the insights a config anchors on directly (by short_id)."""

    name = "anchored_insights"

    def __init__(self, strategy: MovementScoringStrategy) -> None:
        self._strategy = strategy

    def gather(self, team: Team, config: BriefConfig | None, lookback_days: int) -> list[SourceItem]:
        settings = BriefSettings.from_config(config)
        return self._strategy.gather_items(
            self._anchor_insights(team, config), team, lookback_days, settings, source_name=self.name
        )

    def _anchor_insights(self, team: Team, config: BriefConfig | None) -> QuerySet[Insight]:
        insight_short_ids = (config.anchors.get("insights") if config else None) or []
        if not insight_short_ids:
            return Insight.objects.none()
        return Insight.objects.filter(team=team, deleted=False, short_id__in=insight_short_ids).distinct()
