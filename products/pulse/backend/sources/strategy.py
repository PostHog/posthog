from dataclasses import dataclass

from django.db.models import QuerySet

import structlog

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.config import BriefSettings
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Movement:
    significant: bool
    pct_change: float
    baseline_total: float
    current_total: float


def score_movement(*, baseline: list[float], current: list[float], settings: BriefSettings) -> Movement:
    baseline_total = float(sum(baseline))
    current_total = float(sum(current))
    if not baseline or baseline_total < settings.min_baseline_value * len(baseline):
        return Movement(significant=False, pct_change=0.0, baseline_total=baseline_total, current_total=current_total)
    pct_change = ((current_total - baseline_total) / baseline_total) * 100.0
    return Movement(
        significant=abs(pct_change) >= settings.min_abs_change_pct,
        pct_change=pct_change,
        baseline_total=baseline_total,
        current_total=current_total,
    )


class MovementScoringStrategy:
    """Reusable seam turning a set of insights into scored movement items.

    Both AnchoredInsightsSource and AnchoredDashboardsSource hold an instance and call
    ``gather_items`` — the retrieval (which insights) differs per source, the scoring is shared.
    Swappable so an alternative scoring approach can be injected/tested without touching a source.
    """

    def gather_items(
        self, insights: QuerySet[Insight], team: Team, lookback_days: int, settings: BriefSettings, *, source_name: str
    ) -> list[SourceItem]:
        items: list[SourceItem] = []
        for insight in insights[: settings.max_anchor_insights]:
            try:
                items.extend(self._items_for_insight(insight, team, lookback_days, settings, source_name))
            except Exception as exc:
                # One broken insight must not kill the brief; the future resource-health
                # source is what reports on failing insights.
                logger.exception("pulse_anchored_insight_failed", team_id=team.id, insight_short_id=insight.short_id)
                capture_exception(exc, {"team_id": team.id, "insight_short_id": insight.short_id, "product": "pulse"})
        return items

    def _items_for_insight(
        self, insight: Insight, team: Team, lookback_days: int, settings: BriefSettings, source_name: str
    ) -> list[SourceItem]:
        calculation = calculate_for_query_based_insight(
            insight,
            team=team,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=None,
        )
        if not calculation.result:
            return []
        items: list[SourceItem] = []
        label = insight.name or insight.derived_name or ""
        insight_url = f"/project/{team.id}/insights/{insight.short_id}"
        for series_index, series_result in enumerate(calculation.result):
            if not isinstance(series_result, dict) or "data" not in series_result:
                continue  # non-trends result shape — skip
            values = [float(v) for v in series_result["data"][-2 * lookback_days :]]
            if len(values) % 2:
                values = values[1:]  # drop the oldest sample so the two windows compare equal lengths
            if len(values) < 2:
                continue
            half = len(values) // 2
            movement = score_movement(baseline=values[:half], current=values[half:], settings=settings)
            if not movement.significant:
                continue
            direction = "rose" if movement.pct_change > 0 else "dropped"
            display = series_result.get("label") or label or insight.short_id
            items.append(
                SourceItem(
                    source=source_name,
                    kind=SourceItemKind.MOVEMENT,
                    title=f"{display} {direction} {abs(round(movement.pct_change, 1))}%",
                    description=(
                        f"'{display}' {direction} from {movement.baseline_total:g} "
                        f"to {movement.current_total:g} over the last {lookback_days} days vs the prior {lookback_days}."
                    ),
                    metrics={
                        "pct_change": round(movement.pct_change, 1),
                        "baseline_total": movement.baseline_total,
                        "current_total": movement.current_total,
                        "lookback_days": lookback_days,
                    },
                    evidence=[
                        EvidenceRef(type=EvidenceType.INSIGHT, ref=insight.short_id, label=label, url=insight_url)
                    ],
                    fingerprint_hint=f"{insight.short_id}:{series_index}",
                )
            )
        return items
