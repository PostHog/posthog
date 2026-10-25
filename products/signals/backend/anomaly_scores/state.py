"""The stored state of the train and score split, and the choice between a train step and a score step.

A train step fetches the full detector history and stores the newest values of each series. A score
step fetches only the newest buckets and scores them on the stored values. See `AnomalyScoringState`.
"""

import math
import datetime
import dataclasses
from collections.abc import Collection
from typing import Any
from zoneinfo import ZoneInfo

from posthog.schema import IntervalType

from posthog.dataclasses import frozen
from posthog.interval_specs import interval_spec
from posthog.models import Team

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.config import (
    DEFAULT_LIMITS,
    AnomalyScoringConfig,
    ScoringRun,
    resolve_profile,
)
from products.signals.backend.anomaly_scores.scoring import (
    SeriesWindow,
    StateIdentity,
    TrainedState,
    buckets_to_score,
    interval_scoring,
    query_cost,
    scoring_interval,
    state_identity,
    supports_score_step,
    trends_query_for,
)
from products.signals.backend.models import AnomalyScoringState


@frozen
class RunPlan:
    """What one pick does and the ClickHouse queries it sends."""

    queries: int
    # None when the split is off.
    run: ScoringRun | None = None
    refresh_buckets: int = 0


def needs_training(
    state: TrainedState | None,
    *,
    identity: StateIdentity,
    now: datetime.datetime,
    timezone: ZoneInfo,
    train_every: int,
    max_backfill: int,
) -> bool:
    if state is None or state.identity != identity or not state.windows or state.scored_through is None:
        return True
    interval = identity.interval
    if state.trained_at + interval_spec(interval).period * train_every <= now:
        return True
    # More due buckets than one visit scores. A train step scores the newest of them, as a first visit does.
    due = buckets_to_score(
        interval,
        now=now,
        after=state.scored_through,
        timezone=timezone,
        limits=dataclasses.replace(DEFAULT_LIMITS, max_backfill_buckets=max_backfill + 1),
    )
    if due > max_backfill:
        return True
    return state.missing_series * 2 > len(state.windows)


def plan_run(
    insight: Insight, team: Team, state: TrainedState | None, config: AnomalyScoringConfig, now: datetime.datetime
) -> RunPlan:
    queries = query_cost(insight, team)
    if not config.train_score_split:
        return RunPlan(queries=queries)
    try:
        profile = resolve_profile(team, insight)
        query = trends_query_for(insight, profile)
        interval = scoring_interval(query)
        scoring = interval_scoring(profile, interval)
        identity = state_identity(query, scoring, team, config.limits)
    except Exception:
        # The scorer fails on the same query and reports the error. A train step charges the larger budget.
        return RunPlan(queries=queries, run=ScoringRun.TRAIN)
    refresh = config.refresh_buckets.get(interval, 0)
    trains = not supports_score_step(query) or needs_training(
        state,
        identity=identity,
        now=now,
        timezone=team.timezone_info,
        train_every=config.train_every_buckets[interval],
        max_backfill=config.limits.max_backfill_buckets,
    )
    return RunPlan(queries=queries, run=ScoringRun.TRAIN if trains else ScoringRun.SCORE, refresh_buckets=refresh)


def load_states(team: Team, insights: Collection[Insight]) -> dict[int, TrainedState]:
    """Insight id to the stored state of the insight's own scoring profile."""
    profiles = {insight.id: resolve_profile(team, insight).name for insight in insights}
    if not profiles:
        return {}
    rows = AnomalyScoringState.objects.for_team(team.id).filter(insight_id__in=list(profiles))
    return {
        row.insight_id: _from_row(row, team.timezone_info)
        for row in rows
        if profiles.get(row.insight_id) == row.profile
    }


def load_state(team: Team, insight: Insight) -> TrainedState | None:
    return load_states(team, [insight]).get(insight.id)


def save_state(team: Team, insight_id: int, profile: str, state: TrainedState) -> None:
    fields = {
        "interval": state.identity.interval.value,
        "detector_version": state.identity.detector_version,
        "query_hash": state.identity.query_hash,
        "trained_at": state.trained_at,
        "scored_through": state.scored_through,
        "missing_series": state.missing_series,
        "series": {key: _window_json(window) for key, window in state.windows.items()},
    }
    # The scope filters on the project's canonical team, and save() writes that team for a new row.
    AnomalyScoringState.objects.for_team(team.id).update_or_create(
        insight_id=insight_id, profile=profile, defaults=fields, create_defaults={**fields, "team_id": team.id}
    )


def _window_json(window: SeriesWindow) -> dict[str, Any]:
    return {
        "first_bucket": window.first_bucket.isoformat(),
        # JSON has no NaN.
        "values": [value if math.isfinite(value) else None for value in window.values],
    }


def _from_row(row: AnomalyScoringState, timezone: datetime.tzinfo) -> TrainedState:
    windows: dict[str, SeriesWindow] = {}
    for key, stored in (row.series or {}).items():
        try:
            window = SeriesWindow(
                # Bucket starts step in wall-clock time of the project timezone.
                first_bucket=datetime.datetime.fromisoformat(stored["first_bucket"]).astimezone(timezone),
                values=[math.nan if value is None else float(value) for value in stored["values"]],
            )
        except (KeyError, TypeError, ValueError):
            continue
        if window.values:
            windows[key] = window
    return TrainedState(
        identity=StateIdentity(
            interval=IntervalType(row.interval), detector_version=row.detector_version, query_hash=row.query_hash
        ),
        trained_at=row.trained_at,
        scored_through=row.scored_through,
        windows=windows,
        missing_series=row.missing_series,
    )
