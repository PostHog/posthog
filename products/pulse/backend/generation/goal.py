from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet

import structlog

from posthog.models.team import Team

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_insights import (
    calculate_insight_results,
    rate_summary,
    series_daily_values,
    split_score_windows,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GoalStatus:
    """A deterministic distance-to-goal snapshot — computed, never inferred.

    `goal` and `metric_label` carry untrusted user-authored free text; they are sanitized once
    at the prompt-render boundary, the collector stays raw. Rates and `delta_pct` are
    code-computed via the shared anchored-insights window math so the LLM never arithmetics.
    """

    goal: str
    metric_label: str | None
    current_rate: str | None
    previous_rate: str | None
    delta_pct: float | None


def collect_goal_status(team: Team, config: BriefConfig, period_days: int) -> GoalStatus:
    """Compute where the config's goal metric stands: current vs previous per-day rates.

    A metric that can't be read (missing/deleted insight, failing execution, non-trends shape,
    too little data) degrades to the goal text alone — the prompt still states the goal, it
    just carries no figures.
    """
    goal = config.goal.strip()
    text_only = GoalStatus(goal=goal, metric_label=None, current_rate=None, previous_rate=None, delta_pct=None)
    short_id = _metric_short_id(config)
    if short_id is None:
        return text_only
    insight = _metric_insight(team, short_id)
    if insight is None:
        return text_only
    try:
        results = calculate_insight_results(insight, team)
    except Exception:
        # Best-effort by design: a broken metric read must not cost the brief its goal framing.
        logger.exception("pulse_goal_metric_read_failed", team_id=team.id, insight_short_id=short_id)
        return text_only
    windows = _goal_windows(results, period_days)
    if windows is None:
        return text_only
    previous, current = windows
    # Per-day rates, not window totals: the live window can be shorter than period_days when
    # data is sparse, and the delta must agree with the two rates stated beside it.
    previous_rate = float(sum(previous)) / len(previous)
    current_rate = float(sum(current)) / len(current)
    # Zero-baseline guard: a delta off nothing is meaningless, not infinite.
    delta_pct = round(((current_rate - previous_rate) / previous_rate) * 100.0, 1) if previous_rate else None
    return GoalStatus(
        goal=goal,
        metric_label=insight.name or insight.derived_name or insight.short_id,
        current_rate=rate_summary(current_rate),
        previous_rate=rate_summary(previous_rate),
        delta_pct=delta_pct,
    )


def _metric_short_id(config: BriefConfig) -> str | None:
    # Shape re-check in Python even though the API validates on write — rows can be written by
    # other paths, and a malformed metric must degrade, not raise.
    metric = config.goal_metric
    if isinstance(metric, dict) and isinstance(metric.get("insight_short_id"), str) and metric["insight_short_id"]:
        return metric["insight_short_id"]
    return None


def _metric_insight(team: Team, short_id: str) -> Insight | None:
    queryset: QuerySet[Insight] = Insight.objects.filter(team=team, short_id=short_id, deleted=False)
    return queryset.order_by("id").first()  # lowest id wins when a short_id has duplicates


def _goal_windows(results: list[Any], period_days: int) -> tuple[list[float], list[float]] | None:
    # The goal metric is the insight's first series — goal_metric carries no series_index in v1.5.
    if not results:
        return None
    values = series_daily_values(results[0], period_days)
    if values is None:
        return None
    return split_score_windows(values)
