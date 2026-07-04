from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

import structlog

from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import Opportunity
from products.pulse.backend.sources.anchored_insights import calculate_insight_results, split_score_windows

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
    now = now_fn()
    opportunities = (
        Opportunity.objects.for_team(team.pk)
        # metric_ref + baseline isnull filters are the SQL half of the usability gate;
        # _has_usable_refs re-checks the JSON shapes in Python.
        .filter(created_at__lte=now - timedelta(days=MIN_AGE_DAYS), metric_ref__isnull=False, baseline__isnull=False)
        .order_by("-created_at")
    )
    lines: list[OpportunityStatusLine] = []
    for opportunity in opportunities:
        if len(lines) >= MAX_STATUS_LINES:
            break
        if not _has_usable_refs(opportunity):
            continue
        try:
            lines.append(_status_line(opportunity, team, now))
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


def _status_line(opportunity: Opportunity, team: Team, now: datetime) -> OpportunityStatusLine:
    baseline = opportunity.baseline or {}
    then_total = float(baseline["current_total"])
    period_days = int(baseline["period_days"])
    current_total = _current_total(opportunity, team, period_days)
    if current_total is None:
        current_summary = METRIC_UNAVAILABLE
        delta_pct = None
    else:
        current_summary = _per_day_summary(current_total, period_days)
        # Zero-baseline guard: a delta off nothing is meaningless, not infinite.
        delta_pct = round(((current_total - then_total) / then_total) * 100.0, 1) if then_total else None
    return OpportunityStatusLine(
        opportunity_id=str(opportunity.id),
        kind=opportunity.kind,
        status=opportunity.status,
        title=opportunity.title,
        age_days=(now - opportunity.created_at).days,
        baseline_summary=_per_day_summary(then_total, period_days),
        current_summary=current_summary,
        delta_pct=delta_pct,
    )


def _current_total(opportunity: Opportunity, team: Team, period_days: int) -> float | None:
    """Re-run the anchored-insights window math over the metric's current data.

    Returns the current-window total, or None when the metric can no longer be read
    (deleted/renamed insight, non-trends shape, too little data).
    """
    metric_ref = opportunity.metric_ref or {}
    insight = (
        Insight.objects.filter(team=team, short_id=metric_ref["insight_short_id"], deleted=False).order_by("id").first()
    )
    if insight is None:
        return None
    results = calculate_insight_results(insight, team)
    series_index = int(metric_ref.get("series_index", 0))
    if not 0 <= series_index < len(results):
        return None
    series_result = results[series_index]
    if not isinstance(series_result, dict) or "data" not in series_result:
        return None
    windows = split_score_windows([float(v) for v in series_result["data"]], period_days)
    if windows is None:
        return None
    return float(sum(windows[1]))


def _per_day_summary(total: float, period_days: int) -> str:
    return f"{total / period_days:.1f}/day avg"
