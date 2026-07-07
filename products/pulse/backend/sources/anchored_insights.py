from dataclasses import dataclass
from typing import Any

from django.db.models import Q, QuerySet

import structlog

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, SourceItem, build_fingerprint_hint

logger = structlog.get_logger(__name__)

MIN_ABS_CHANGE_PCT = 20.0
MIN_BASELINE_VALUE = 10.0
MAX_ANCHOR_INSIGHTS = 10
FALLBACK_DASHBOARD_COUNT = 3


@dataclass(frozen=True)
class Movement:
    significant: bool
    pct_change: float
    baseline_total: float
    current_total: float


def calculate_insight_results(insight: Insight, team: Team) -> list[Any]:
    """Insight execution shared by gathering and accountability re-scoring — one execution
    mode so a brief and its later then-vs-now check read the metric the same way."""
    calculation = calculate_for_query_based_insight(
        insight,
        team=team,
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user=None,
    )
    return calculation.result if isinstance(calculation.result, list) else []


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

    Shared by gathering and accountability re-scoring so "current" always means the same window
    math the movement was originally scored with. Callers trim the series to 2×period_days via
    series_daily_values before calling this. Returns None when there is too little data.
    """
    if len(values) % 2:
        values = values[1:]  # drop the oldest sample so the two windows compare equal lengths
    if len(values) < 2:
        return None
    half = len(values) // 2
    return values[:half], values[half:]


def score_movement(*, baseline: list[float], current: list[float]) -> Movement:
    baseline_total = float(sum(baseline))
    current_total = float(sum(current))
    if not baseline or baseline_total < MIN_BASELINE_VALUE * len(baseline):
        return Movement(significant=False, pct_change=0.0, baseline_total=baseline_total, current_total=current_total)
    pct_change = ((current_total - baseline_total) / baseline_total) * 100.0
    return Movement(
        significant=abs(pct_change) >= MIN_ABS_CHANGE_PCT,
        pct_change=pct_change,
        baseline_total=baseline_total,
        current_total=current_total,
    )


class AnchoredInsightsSource:
    name = "anchored_insights"

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]:
        items: list[SourceItem] = []
        for insight in self._anchor_insights(team, config)[:MAX_ANCHOR_INSIGHTS]:
            try:
                items.extend(self._items_for_insight(insight, team, period_days))
            except Exception:
                # One broken insight must not kill the brief; the future resource-health
                # source is what reports on failing insights.
                logger.exception("pulse_anchored_insight_failed", team_id=team.id, insight_short_id=insight.short_id)
        return items

    def _anchor_insights(self, team: Team, config: BriefConfig | None) -> QuerySet[Insight]:
        anchors = config.anchors if config else {}
        insight_short_ids = anchors.get("insights") or []
        dashboard_ids = anchors.get("dashboards") or []
        if insight_short_ids or dashboard_ids:
            anchor_filter = Q()
            if insight_short_ids:
                anchor_filter |= Q(short_id__in=insight_short_ids)
            if dashboard_ids:
                anchor_filter |= Q(dashboards__id__in=dashboard_ids)
            return Insight.objects.filter(team=team, deleted=False).filter(anchor_filter).distinct()
        # Zero-config default: insights on the team's most recently accessed dashboards.
        fallback_dashboards = Dashboard.objects.filter(
            team=team, deleted=False, last_accessed_at__isnull=False
        ).order_by("-last_accessed_at")[:FALLBACK_DASHBOARD_COUNT]
        return Insight.objects.filter(team=team, deleted=False, dashboards__in=fallback_dashboards).distinct()

    def _items_for_insight(self, insight: Insight, team: Team, period_days: int) -> list[SourceItem]:
        items: list[SourceItem] = []
        label = insight.name or insight.derived_name or ""
        for series_index, series_result in enumerate(calculate_insight_results(insight, team)):
            values = series_daily_values(series_result, period_days)
            if values is None:
                continue  # non-trends result shape — skip
            windows = split_score_windows(values)
            if windows is None:
                continue
            movement = score_movement(baseline=windows[0], current=windows[1])
            if not movement.significant:
                continue
            direction = "rose" if movement.pct_change > 0 else "dropped"
            display = series_result.get("label") or label or insight.short_id
            items.append(
                SourceItem(
                    source=self.name,
                    kind="movement",
                    title=f"{display} {direction} {abs(round(movement.pct_change, 1))}%",
                    description=(
                        f"'{display}' {direction} from {movement.baseline_total:g} "
                        f"to {movement.current_total:g} over the last {period_days} days vs the prior {period_days}."
                    ),
                    numbers={
                        "pct_change": round(movement.pct_change, 1),
                        "baseline_total": movement.baseline_total,
                        "current_total": movement.current_total,
                        "period_days": period_days,
                    },
                    evidence=[EvidenceRef(type="insight", ref=insight.short_id, label=label)],
                    fingerprint_hint=build_fingerprint_hint(self.name, insight.short_id, str(series_index)),
                )
            )
        return items
