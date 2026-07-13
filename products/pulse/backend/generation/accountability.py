import time
from collections.abc import Callable
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

import structlog

from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.metrics import pct_delta, per_day_rate, rate_summary
from products.pulse.backend.models import Opportunity
from products.pulse.backend.sources.anchored_insights import (
    InsightResultsCache,
    resolve_metric_insights,
    series_daily_values,
    split_score_windows,
)

logger = structlog.get_logger(__name__)

MIN_AGE_DAYS = 7
MAX_STATUS_LINES = 10
METRIC_UNAVAILABLE = "metric no longer available"

# Cap the whole re-scoring pass so the LLM call after it keeps its slice of the 5-min activity;
# the per-insight wall-clock cap lives on InsightResultsCache in sources/anchored_insights.py.
_RESCORE_BUDGET_SECONDS = 45


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


def collect_accountability(
    team: Team,
    min_age_days: int = MIN_AGE_DAYS,
    now_fn: Callable[[], datetime] = timezone.now,
    results_cache: InsightResultsCache | None = None,
) -> list[OpportunityStatusLine]:
    """Re-score past opportunities against their creation-time baselines.

    The opportunity set is team-wide (opportunities carry no config affinity in the model), but
    the age gate is caller-supplied so a slower-cadence config can wait longer before grading its
    own suggestions.
    """
    now = now_fn()
    rows = (
        Opportunity.objects.for_team(team.pk)
        # isnull filters are the SQL half of the usability gate; _has_usable_refs re-checks the
        # JSON shapes in Python. The 2x overscan bounds the fetch — rows are permanent dedup
        # tombstones, so an uncapped scan grows with team history.
        .filter(created_at__lte=now - timedelta(days=min_age_days), metric_ref__isnull=False, baseline__isnull=False)
        .order_by("-created_at")[: MAX_STATUS_LINES * 2]
    )
    usable = [row for row in rows if _has_usable_refs(row)]
    insights = resolve_metric_insights(team, {opportunity.metric_ref["insight_short_id"] for opportunity in usable})
    results_cache = results_cache or InsightResultsCache(team)
    lines: list[OpportunityStatusLine] = []
    started_at = time.monotonic()
    for opportunity in usable:
        # The attempt budget also caps blocking insight executions when lines keep failing —
        # failed lines don't count toward the line cap, but their executions still cost time.
        if len(lines) >= MAX_STATUS_LINES or results_cache.attempts >= MAX_STATUS_LINES:
            break
        # A cumulative wall-clock ceiling on top of the per-insight timeout: many slow-but-not-
        # timing-out queries must still leave the LLM call its share of the 5-minute activity.
        if time.monotonic() - started_at > _RESCORE_BUDGET_SECONDS:
            logger.warning("pulse_accountability_budget_exceeded", team_id=team.id, scored=len(lines))
            break
        try:
            lines.append(_status_line(opportunity, now, insights, results_cache))
        except Exception:
            # One broken re-score must not blank the rest of the accountability section.
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


def _status_line(
    opportunity: Opportunity,
    now: datetime,
    insights: dict[str, Insight],
    results_cache: InsightResultsCache,
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
        current_rate = per_day_rate(window)
        current_summary = rate_summary(current_rate)
        delta_pct = pct_delta(current_rate, then_rate)
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
    results_cache: InsightResultsCache,
) -> list[float] | None:
    """Re-run the anchored-insights window math over the metric's current data.

    Returns the current-window daily values, or None when the metric can no longer be read
    (deleted/renamed insight, non-trends shape, too little data).

    Assumes the insight uses a rolling date range, so re-running it shifts the window to "now".
    A fixed-date-range insight returns the same series forever and re-scores to delta ≈ 0,
    which reads as "no change" — a known v1 limitation.
    """
    short_id = opportunity.metric_ref["insight_short_id"]
    insight = insights.get(short_id)
    if insight is None:
        # Info logs on the unavailable branches (mirrors collect_goal_status): a quietly broken
        # re-score metric must be queryable, not just visible as METRIC_UNAVAILABLE prose.
        logger.info(
            "pulse_accountability_insight_missing",
            team_id=opportunity.team_id,
            opportunity_id=str(opportunity.id),
            insight_short_id=short_id,
        )
        return None
    try:
        results = results_cache.results_for(insight)
    except FuturesTimeoutError:
        # A stuck query degrades to "metric no longer available", not a blanked activity.
        logger.warning("pulse_accountability_insight_timeout", insight_short_id=short_id)
        return None
    series_index = int(opportunity.metric_ref.get("series_index", 0))
    if 0 <= series_index < len(results):
        values = series_daily_values(results[series_index], period_days)
        if values is not None:
            windows = split_score_windows(values)
            if windows is not None:
                return windows[1]
    logger.info(
        "pulse_accountability_metric_unreadable",
        team_id=opportunity.team_id,
        opportunity_id=str(opportunity.id),
        insight_short_id=short_id,
    )
    return None
