from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Literal

import structlog

from posthog.models.team import Team

from products.pulse.backend.generation.metrics import pct_delta, per_day_rate, rate_summary
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.anchored_insights import (
    InsightResultsCache,
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

    `goal`/`metric_label` are untrusted free text, sanitized at the prompt-render boundary.
    `insight_short_id` is set whenever a valid-shaped ref exists (even when unreadable) so the
    next stage can investigate the metric itself.
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

    None only when the config carries no goal — a defensive gate against a blank goal written
    outside the API, since goals are required there. A metric that can't be read (missing/deleted insight, failing or
    malformed execution, non-trends shape, too little data) yields metric_state="unavailable": the
    prompt still states the goal, just without figures.
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
        # Windowing stays inside the try: a malformed data point (e.g. a null in the series) raises
        # in float() conversion, and that must degrade to "unavailable" like any other read failure
        # — not propagate and cost the brief its goal framing entirely.
        windows = _goal_windows(cache.results_for(insight), period_days)
    except FuturesTimeoutError:
        # An expected timeout, not a bug — log at warning like the accountability path so a systemic
        # "goal insights all timing out" pattern is queryable without a stack trace per occurrence.
        logger.warning("pulse_goal_metric_insight_timeout", team_id=team.id, insight_short_id=short_id)
        return unavailable
    except Exception:
        logger.exception("pulse_goal_metric_read_failed", team_id=team.id, insight_short_id=short_id)
        return unavailable
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
    # other paths, and a malformed metric must degrade, not raise. Dispatches on the stored "type"
    # discriminator (absent on legacy rows → treated as "insight"); other types are unread in v1.
    metric = config.goal_metric
    if not isinstance(metric, dict) or metric.get("type", "insight") != "insight":
        return None
    short_id = metric.get("insight_short_id")
    return short_id if isinstance(short_id, str) and short_id else None


def _goal_windows(results: list[Any], period_days: int) -> tuple[list[float], list[float]] | None:
    if not results:
        return None
    values = series_daily_values(results[0], period_days)
    if values is None:
        return None
    return split_score_windows(values)
