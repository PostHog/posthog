"""The stored state of the train and score split, and the choice between a train step and a score step.

A train step fetches the training history, fits one detector artifact per series, and stores them as
one blob. A score step fetches only the newest buckets and scores them with the stored artifacts. See
`AnomalyScoringState` and `artifacts.py`.
"""

import datetime
import dataclasses
from collections.abc import Collection
from zoneinfo import ZoneInfo

import structlog

from posthog.schema import IntervalType

from posthog.dataclasses import frozen
from posthog.interval_specs import interval_spec
from posthog.models import Team

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.artifacts import delete_artifacts
from products.signals.backend.anomaly_scores.config import (
    DEFAULT_LIMITS,
    AnomalyScoringConfig,
    ScoringRun,
    resolve_profile,
)
from products.signals.backend.anomaly_scores.scoring import (
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

logger = structlog.get_logger(__name__)


@frozen
class RunPlan:
    """What one pick does and the ClickHouse queries it sends."""

    queries: int
    # None when the split is off.
    run: ScoringRun | None = None


def _schedule_needs_training(
    interval: IntervalType,
    *,
    trained_at: datetime.datetime,
    scored_through: datetime.datetime,
    missing_series: int,
    series_count: int,
    now: datetime.datetime,
    timezone: ZoneInfo,
    train_every: int,
    max_backfill: int,
) -> bool:
    """The retrain triggers that a state row answers alone, without the insight's query."""
    if trained_at + interval_spec(interval).period * train_every <= now:
        return True
    # More due buckets than one visit scores. A train step scores the newest of them, as a first visit does.
    due = buckets_to_score(
        interval,
        now=now,
        after=scored_through,
        timezone=timezone,
        limits=dataclasses.replace(DEFAULT_LIMITS, max_backfill_buckets=max_backfill + 1),
    )
    if due > max_backfill:
        return True
    return missing_series * 2 > series_count


def needs_training(
    state: TrainedState | None,
    *,
    identity: StateIdentity,
    now: datetime.datetime,
    timezone: ZoneInfo,
    train_every: int,
    max_backfill: int,
) -> bool:
    if (
        state is None
        or state.identity != identity
        or not state.series_keys
        or not state.artifact_key
        or state.scored_through is None
    ):
        return True
    return _schedule_needs_training(
        identity.interval,
        trained_at=state.trained_at,
        scored_through=state.scored_through,
        missing_series=state.missing_series,
        series_count=len(state.series_keys),
        now=now,
        timezone=timezone,
        train_every=train_every,
        max_backfill=max_backfill,
    )


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
    trains = not supports_score_step(query) or needs_training(
        state,
        identity=identity,
        now=now,
        timezone=team.timezone_info,
        train_every=config.train_every_buckets[interval],
        max_backfill=config.limits.max_backfill_buckets,
    )
    return RunPlan(queries=queries, run=ScoringRun.TRAIN if trains else ScoringRun.SCORE)


def load_states(team: Team, insights: Collection[Insight]) -> dict[int, TrainedState]:
    """Insight id to the stored state of the insight's own scoring profile."""
    profiles = {insight.id: resolve_profile(team, insight).name for insight in insights}
    if not profiles:
        return {}
    rows = AnomalyScoringState.objects.for_team(team.id).filter(insight_id__in=list(profiles))
    return {row.insight_id: _from_row(row) for row in rows if profiles.get(row.insight_id) == row.profile}


def scored_through_by_insight(
    team: Team, insight_ids: Collection[int], config: AnomalyScoringConfig, now: datetime.datetime
) -> dict[int, datetime.datetime]:
    """Insight id to the newest scored bucket of its stored state, for the rows that a score step can read.

    A row whose retrain is due by age, by due buckets or by missing series is left out, so its insight goes to
    the train pass without a plan. The identity and the profile are not checked here, because they need the
    insight's query. `plan_run` checks them, and the score pass hands an insight that fails them to the train pass.
    """
    if not insight_ids:
        return {}
    rows = (
        AnomalyScoringState.objects.for_team(team.id)
        .filter(insight_id__in=list(insight_ids), scored_through__isnull=False)
        .exclude(artifact_key="")
        .exclude(series_keys=[])
        .values_list("insight_id", "interval", "trained_at", "scored_through", "missing_series", "series_keys")
    )
    scored: dict[int, datetime.datetime] = {}
    scorable = {interval.value: interval for interval in config.train_every_buckets}
    for insight_id, interval, trained_at, scored_through, missing_series, series_keys in rows:
        if scored_through is None or interval not in scorable:
            continue
        if _schedule_needs_training(
            scorable[interval],
            trained_at=trained_at,
            scored_through=scored_through,
            missing_series=missing_series,
            series_count=len(series_keys),
            now=now,
            timezone=team.timezone_info,
            train_every=config.train_every_buckets[scorable[interval]],
            max_backfill=config.limits.max_backfill_buckets,
        ):
            continue
        scored[insight_id] = max(scored_through, scored.get(insight_id, scored_through))
    return scored


def load_state(team: Team, insight: Insight) -> TrainedState | None:
    return load_states(team, [insight]).get(insight.id)


def save_state(team: Team, insight_id: int, profile: str, state: TrainedState) -> None:
    """Write the state row. A new artifact blob replaces the previous one, which is deleted after the write."""
    scope = AnomalyScoringState.objects.for_team(team.id)
    previous_key = scope.filter(insight_id=insight_id, profile=profile).values_list("artifact_key", flat=True).first()
    fields = {
        "interval": state.identity.interval.value,
        "detector_version": state.identity.detector_version,
        "query_hash": state.identity.query_hash,
        "trained_at": state.trained_at,
        "scored_through": state.scored_through,
        "missing_series": state.missing_series,
        "artifact_key": state.artifact_key,
        "artifact_sha256": state.artifact_sha256,
        "series_keys": list(state.series_keys),
    }
    # The scope filters on the project's canonical team, and save() writes that team for a new row.
    scope.update_or_create(
        insight_id=insight_id, profile=profile, defaults=fields, create_defaults={**fields, "team_id": team.id}
    )
    if previous_key and previous_key != state.artifact_key:
        try:
            delete_artifacts(previous_key)
        except Exception:
            # The row no longer names the blob, so a failed delete leaves an unread blob and nothing else.
            logger.warning("anomaly_scoring_artifact_delete_failed", insight_id=insight_id, exc_info=True)


def invalidate_state(team: Team, insight_id: int, profile: str) -> None:
    """Make the next visit of the insight train. The row keeps its blob key, so that train step deletes the blob."""
    AnomalyScoringState.objects.for_team(team.id).filter(insight_id=insight_id, profile=profile).update(series_keys=[])


def _from_row(row: AnomalyScoringState) -> TrainedState:
    series_keys = row.series_keys if isinstance(row.series_keys, list) else []
    return TrainedState(
        identity=StateIdentity(
            interval=IntervalType(row.interval), detector_version=row.detector_version, query_hash=row.query_hash
        ),
        trained_at=row.trained_at,
        scored_through=row.scored_through,
        series_keys=tuple(str(key) for key in series_keys),
        artifact_key=row.artifact_key,
        artifact_sha256=row.artifact_sha256,
        missing_series=row.missing_series,
    )
