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
    # Memoized per short_id: per-brief re-scoring cost is bounded at one cached-execution-mode
    # insight run per distinct insight, so parallelizing the calls is not worth the machinery.
    results_cache: dict[str, list[Any]] = {}
    lines: list[OpportunityStatusLine] = []
    for opportunity in usable:
        if len(lines) >= MAX_STATUS_LINES:
            break
        try:
            lines.append(_status_line(opportunity, team, now, insights, results_cache))
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
    team: Team,
    now: datetime,
    insights: dict[str, Insight],
    results_cache: dict[str, list[Any]],
) -> OpportunityStatusLine:
    baseline = opportunity.baseline
    then_total = float(baseline["current_total"])
    period_days = int(baseline["period_days"])
    window = _current_window(opportunity, team, period_days, insights, results_cache)
    if window is None:
        current_summary = METRIC_UNAVAILABLE
        delta_pct = None
    else:
        current_total = float(sum(window))
        # The live window can be shorter than period_days when data is sparse — average over
        # what was actually read.
        current_summary = _per_day_summary(current_total, len(window))
        # Zero-baseline guard: a delta off nothing is meaningless, not infinite. Deliberately
        # different from score_movement's volume floor — this compares against a snapshot, it
        # is not a significance test.
        delta_pct = round(((current_total - then_total) / then_total) * 100.0, 1) if then_total else None
    return OpportunityStatusLine(
        opportunity_id=str(opportunity.id),
        kind=opportunity.kind,
        status=opportunity.status,
        title=opportunity.title,
        age_days=(now - opportunity.created_at).days,
        # period_days is the only denominator the snapshot recorded.
        baseline_summary=_per_day_summary(then_total, period_days),
        current_summary=current_summary,
        delta_pct=delta_pct,
    )


def _current_window(
    opportunity: Opportunity,
    team: Team,
    period_days: int,
    insights: dict[str, Insight],
    results_cache: dict[str, list[Any]],
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
        return None
    if short_id not in results_cache:
        # A raising execution is deliberately not cached: the per-line handler logs it, and a
        # later line on the same insight retries (bounded by the line cap).
        results_cache[short_id] = calculate_insight_results(insight, team)
    results = results_cache[short_id]
    series_index = int(opportunity.metric_ref.get("series_index", 0))
    if not 0 <= series_index < len(results):
        return None
    values = series_daily_values(results[series_index], period_days)
    if values is None:
        return None
    windows = split_score_windows(values, period_days)
    if windows is None:
        return None
    return windows[1]


def _per_day_summary(total: float, days: int) -> str:
    return f"{total / days:.1f}/day avg"
