from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

import structlog

from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import Opportunity
from products.pulse.backend.sources.anchored_insights import (
    calculate_insight_results,
    rate_summary,
    series_daily_values,
    split_score_windows,
)

logger = structlog.get_logger(__name__)

MIN_AGE_DAYS = 7
MAX_STATUS_LINES = 10
METRIC_UNAVAILABLE = "metric no longer available"


@dataclass(frozen=True)
class OpportunityStatusLine:
    """A then-vs-now status line for a previously surfaced opportunity — computed, never inferred.

    `title` carries untrusted free text (LLM-authored opportunity titles); it is sanitized once
    at the prompt-render boundary, the collector stays raw. Summaries and `delta_pct` are
    deterministic so the LLM never arithmetics, and `delta_pct` is a naive then-vs-now delta —
    v1 makes no causal claims.
    """

    opportunity_id: str
    kind: str
    status: str
    title: str
    age_days: int
    baseline_summary: str
    current_summary: str
    delta_pct: float | None


class _InsightResultsCache:
    """Memoizes insight executions per short_id and counts every attempt (success or raise).

    Memoization bounds the happy path at one cached-execution-mode run per distinct insight
    (so parallelizing the calls is not worth the machinery); the attempt count lets the
    collector budget the failure path too, keeping re-scoring latency bounded inside the
    synthesize activity's shared 5-minute timeout.
    """

    def __init__(self, team: Team) -> None:
        self._team = team
        self._results: dict[str, list[Any]] = {}
        self.attempts = 0

    def results_for(self, insight: Insight) -> list[Any]:
        if insight.short_id not in self._results:
            # A raising execution is deliberately not cached: the per-line handler logs it,
            # and a retry on a later line still counts against the attempt budget.
            self.attempts += 1
            self._results[insight.short_id] = calculate_insight_results(insight, self._team)
        return self._results[insight.short_id]


def collect_accountability(team: Team, now_fn: Callable[[], datetime] = timezone.now) -> list[OpportunityStatusLine]:
    """Re-score past opportunities against their creation-time baselines.

    Team-wide, not config-scoped: opportunities carry no config affinity in the model, so every
    brief sees the same accountability list (per-focus scoping is a recorded follow-up).
    """
    now = now_fn()
    rows = (
        Opportunity.objects.for_team(team.pk)
        # isnull filters are the SQL half of the usability gate; _has_usable_refs re-checks the
        # JSON shapes in Python. The 2x overscan bounds the fetch — rows are permanent dedup
        # tombstones, so an uncapped scan grows with team history.
        .filter(created_at__lte=now - timedelta(days=MIN_AGE_DAYS), metric_ref__isnull=False, baseline__isnull=False)
        .order_by("-created_at")[: MAX_STATUS_LINES * 2]
    )
    usable = [row for row in rows if _has_usable_refs(row)]
    insights = _insights_by_short_id(team, usable)
    results_cache = _InsightResultsCache(team)
    lines: list[OpportunityStatusLine] = []
    for opportunity in usable:
        # The attempt budget also caps blocking insight executions when lines keep failing —
        # failed lines don't count toward the line cap, but their executions still cost time.
        if len(lines) >= MAX_STATUS_LINES or results_cache.attempts >= MAX_STATUS_LINES:
            break
        try:
            lines.append(_status_line(opportunity, now, insights, results_cache))
        except Exception:
            # Symmetry with explain's per-collector isolation: one broken re-score must not
            # blank the rest of the accountability section.
            logger.exception("pulse_accountability_line_failed", team_id=team.id, opportunity_id=str(opportunity.id))
    return lines


def _has_usable_refs(opportunity: Opportunity) -> bool:
    metric_ref = opportunity.metric_ref
    baseline = opportunity.baseline
    return (
        isinstance(metric_ref, dict)
        and bool(metric_ref.get("insight_short_id"))
        and isinstance(baseline, dict)
        and isinstance(baseline.get("current_total"), int | float)
        and isinstance(baseline.get("period_days"), int | float)
        and baseline["period_days"] > 0
    )


def _insights_by_short_id(team: Team, opportunities: list[Opportunity]) -> dict[str, Insight]:
    short_ids = {opportunity.metric_ref["insight_short_id"] for opportunity in opportunities}
    insights: dict[str, Insight] = {}
    for insight in Insight.objects.filter(team=team, short_id__in=short_ids, deleted=False).order_by("id"):
        insights.setdefault(insight.short_id, insight)  # lowest id wins when a short_id has duplicates
    return insights


def _status_line(
    opportunity: Opportunity,
    now: datetime,
    insights: dict[str, Insight],
    results_cache: _InsightResultsCache,
) -> OpportunityStatusLine:
    baseline = opportunity.baseline
    period_days = int(baseline["period_days"])
    # period_days is the only denominator the snapshot recorded.
    then_rate = float(baseline["current_total"]) / period_days
    window = _current_window(opportunity, period_days, insights, results_cache)
    if window is None:
        current_summary = METRIC_UNAVAILABLE
        delta_pct = None
    else:
        # The live window can be shorter than period_days when data is sparse — average over
        # what was actually read, and compare per-day rates so the delta always agrees with
        # the two summaries beside it.
        current_rate = float(sum(window)) / len(window)
        current_summary = rate_summary(current_rate)
        # Zero-baseline guard: a delta off nothing is meaningless, not infinite. Deliberately
        # different from score_movement's volume floor — this compares against a snapshot, it
        # is not a significance test.
        delta_pct = round(((current_rate - then_rate) / then_rate) * 100.0, 1) if then_rate else None
    return OpportunityStatusLine(
        opportunity_id=str(opportunity.id),
        kind=opportunity.kind,
        status=opportunity.status,
        title=opportunity.title,
        age_days=(now - opportunity.created_at).days,
        baseline_summary=rate_summary(then_rate),
        current_summary=current_summary,
        delta_pct=delta_pct,
    )


def _current_window(
    opportunity: Opportunity,
    period_days: int,
    insights: dict[str, Insight],
    results_cache: _InsightResultsCache,
) -> list[float] | None:
    """Re-run the anchored-insights window math over the metric's current data.

    Returns the current-window daily values, or None when the metric can no longer be read
    (deleted/renamed insight, non-trends shape, too little data).

    Assumes the insight uses a rolling date range, so re-running it shifts the window to "now".
    A fixed-date-range insight returns the same series forever and re-scores to delta ≈ 0,
    which reads as "no change" — a known v1 limitation.
    """
    insight = insights.get(opportunity.metric_ref["insight_short_id"])
    if insight is None:
        return None
    results = results_cache.results_for(insight)
    series_index = int(opportunity.metric_ref.get("series_index", 0))
    if not 0 <= series_index < len(results):
        return None
    values = series_daily_values(results[series_index], period_days)
    if values is None:
        return None
    windows = split_score_windows(values)
    if windows is None:
        return None
    return windows[1]
