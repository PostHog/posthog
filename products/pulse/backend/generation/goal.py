from dataclasses import dataclass
from typing import Any, Literal

import structlog

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_insights import (
    InsightResultsCache,
    pct_delta,
    per_day_rate,
    rate_summary,
    resolve_metric_insight,
    series_daily_values,
    split_score_windows,
)

logger = structlog.get_logger(__name__)

# "none": no metric configured (qualitative goal). "ok": figures below are populated.
# "unavailable": a metric is configured but could not be read this period — itself an
# investigable signal, so it must stay distinguishable from "none" downstream.
MetricState = Literal["none", "ok", "unavailable"]


@dataclass(frozen=True)
class GoalStatus:
    """A deterministic distance-to-goal snapshot — computed, never inferred.

    `goal` and `metric_label` carry untrusted user-authored free text; they are sanitized once
    at the prompt-render boundary, the collector stays raw. Rates and `delta_pct` are
    code-computed via the shared anchored-insights window math so the LLM never arithmetics.
    `insight_short_id` is the configured metric ref (set whenever a valid-shaped ref exists,
    even when unreadable) so downstream consumers can investigate the metric itself.
    """

    goal: str
    metric_state: MetricState = "none"
    insight_short_id: str | None = None
    metric_label: str | None = None
    current_rate: str | None = None
    previous_rate: str | None = None
    delta_pct: float | None = None


def collect_goal_status(
    team: Team, config: BriefConfig, period_days: int, results_cache: InsightResultsCache | None = None
) -> GoalStatus | None:
    """Compute where the config's goal metric stands: current vs previous per-day rates.

    None when the config has no goal — the single gate for blank goals. A metric that can't be
    read (missing/deleted insight, failing execution, non-trends shape, too little data) yields
    metric_state="unavailable": the prompt still states the goal, just without figures.
    """
    goal = config.goal.strip()
    if not goal:
        return None
    short_id = _metric_short_id(config)
    if short_id is None:
        return GoalStatus(goal=goal)
    unavailable = GoalStatus(goal=goal, metric_state="unavailable", insight_short_id=short_id)
    insight = resolve_metric_insight(team, short_id)
    if insight is None:
        # Info logs on every unavailable branch: "the user's goal metric quietly broke" must be
        # queryable, not just visible as a figure-less brief.
        logger.info("pulse_goal_metric_insight_missing", team_id=team.id, insight_short_id=short_id)
        return unavailable
    cache = results_cache or InsightResultsCache(team)
    try:
        results = cache.results_for(insight)
    except Exception:
        # Best-effort by design: a broken metric read must not cost the brief its goal framing.
        logger.exception("pulse_goal_metric_read_failed", team_id=team.id, insight_short_id=short_id)
        return unavailable
    windows = _goal_windows(results, period_days)
    if windows is None:
        logger.info("pulse_goal_metric_unreadable", team_id=team.id, insight_short_id=short_id)
        return unavailable
    previous, current = windows
    previous_rate = per_day_rate(previous)
    current_rate = per_day_rate(current)
    return GoalStatus(
        goal=goal,
        metric_state="ok",
        insight_short_id=short_id,
        metric_label=insight.name or insight.derived_name or insight.short_id,
        current_rate=rate_summary(current_rate),
        previous_rate=rate_summary(previous_rate),
        delta_pct=pct_delta(current_rate, previous_rate),
    )


def _metric_short_id(config: BriefConfig) -> str | None:
    # Shape re-check in Python even though the API validates on write — rows can be written by
    # other paths, and a malformed metric must degrade, not raise.
    metric = config.goal_metric
    if isinstance(metric, dict) and isinstance(metric.get("insight_short_id"), str) and metric["insight_short_id"]:
        return metric["insight_short_id"]
    return None


def _goal_windows(results: list[Any], period_days: int) -> tuple[list[float], list[float]] | None:
    # The goal metric is the insight's first series — goal_metric carries no series_index in v1.5.
    if not results:
        return None
    values = series_daily_values(results[0], period_days)
    if values is None:
        return None
    return split_score_windows(values)
