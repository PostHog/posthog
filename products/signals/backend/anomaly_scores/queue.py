"""Pick the active insights that the next anomaly scoring tick scores.

One query per team reads the newest scored bucket of each series back from the `$anomaly_score`
events. `selection.pick_order` then orders the due insights, and the tick picks from that order the
insights whose queries fit the hourly budgets. With the train and score split on, `state.plan_run`
makes each pick a train step or a score step, and each kind has its own budgets.

With the split on, the tick runs two passes, each with its own order and pick cap. The score pass goes
first: it takes the trained insights from their stored state, longest overdue first, so cheap score steps
keep them current. The train pass then takes the other due insights in the `pick_order` order. An insight
whose model is due for a soft retrain goes to the train pass first. When the train pass does not pick it,
the score pass scores it with the old model, so the train budget does not decide the score coverage.
"""

import time
import datetime
import itertools
import dataclasses
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from enum import StrEnum
from typing import Any, cast

from django.core.cache import cache

import structlog

from posthog.schema import ChartDisplayType, IntervalType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.interval_specs import interval_spec
from posthog.models import Team
from posthog.tasks.alerts.utils import NON_TIME_SERIES_DISPLAY_TYPES

from products.alerts.backend.facade.api import enabled_alert_insight_ids
from products.alerts_platform.backend.facade.scheduling import CalendarInterval, alert_check_offset
from products.dashboards.backend.facade.api import insight_ids_on_dashboards_accessed_since
from products.product_analytics.backend.facade.api import (
    insight_ids_modified_since,
    insight_ids_viewed_since,
    insights_including_soft_deleted_for_team,
    saved_trends_insights,
)
from products.signals.backend.anomaly_scores.config import AnomalyScoringConfig, ScoringRun, in_rollout
from products.signals.backend.anomaly_scores.scoring import bucket_end
from products.signals.backend.anomaly_scores.selection import (
    Candidate,
    InsightUsage,
    ScoreCandidate,
    SelectionConfig,
    insight_usage,
    pick_order,
    score_order,
)
from products.signals.backend.anomaly_scores.state import RunPlan, load_states, plan_run, score_ready_by_insight
from products.signals.backend.models import SignalTeamConfig
from products.subscriptions.backend.facade.api import insight_ids_with_active_subscriptions

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

logger = structlog.get_logger(__name__)

SCORE_EVENT = "$anomaly_score"
SOURCE_INSIGHT = "insight"
# One row is one series. Far more than the series of every active insight of one team.
_MAX_SCORED_SERIES = 50_000
# An insight is not picked again in this time after an attempt. Events take a moment to reach
# ClickHouse, and an insight that writes nothing would otherwise stay at the head of the queue.
ATTEMPT_COOLDOWN = datetime.timedelta(hours=1)
# For a failure that the next hour does not fix: an unsupported shape, a query that is too expensive, or no access.
SKIP_COOLDOWN = datetime.timedelta(days=1)
# A query counter lives a little longer than its clock hour, so a tick at the end of the hour still reads it.
# A lost counter lets the scorer spend at most one more hour of budget.
_BUDGET_TTL = datetime.timedelta(minutes=70)

_CALENDAR_INTERVALS = {
    IntervalType.HOUR: CalendarInterval.HOURLY,
    IntervalType.DAY: CalendarInterval.DAILY,
    IntervalType.WEEK: CalendarInterval.WEEKLY,
    IntervalType.MONTH: CalendarInterval.MONTHLY,
}
# A scored-buckets query that hits a ClickHouse limit skips its team for the tick, so the other teams still get picks.
# The cluster memory limit is a subclass of the query memory limit.
_SCORED_BUCKETS_LIMIT_ERRORS = (
    ClickHouseAtCapacity,
    ClickHouseQueryTimeOut,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
)
# After this many teams get a full cluster in one plan, no more teams load. The plan uses the teams it has.
_MAX_AT_CAPACITY_TEAMS = 2
# The last scored state load of a team. The team that waited longest loads first, so a plan that stops early
# does not drop the same teams on every tick.
_TEAM_LOADED_TTL = datetime.timedelta(days=1)
# The scorer rejects these, so selection leaves them out instead of picking them on every tick.
_UNSCORED_DISPLAYS = sorted(
    display.value for display in {*NON_TIME_SERIES_DISPLAY_TYPES, ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE}
)

_SCORED_BUCKETS_QUERY = """
SELECT
    toInt(properties.$anomaly_insight_id) AS insight_id,
    toString(properties.$anomaly_series_key) AS series_key,
    max(timestamp) AS newest_bucket
FROM events
WHERE event = {event}
    AND timestamp >= {since}
    AND timestamp <= {now}
    AND properties.$anomaly_source = {source}
    AND {windows}
GROUP BY insight_id, series_key
LIMIT {limit}
"""


class ActivityReason(StrEnum):
    """Why an insight is active. An insight with no reason in the window is not scored."""

    VIEWED = "viewed"
    DASHBOARD_ACCESSED = "dashboard_accessed"
    ENABLED_ALERT = "enabled_alert"
    ACTIVE_SUBSCRIPTION = "active_subscription"
    EDITED = "edited"


@frozen
class ActiveInsight:
    team_id: int
    insight_id: int
    interval: IntervalType
    reasons: frozenset[ActivityReason] = frozenset()


@frozen
class InsightPick:
    team_id: int
    insight_id: int
    # The newest scored bucket start of each series, in UTC. Empty when the insight was never scored.
    scored_through: dict[str, datetime.datetime]
    interval: IntervalType | None = None
    # The ClickHouse queries this pick sends. Selection charges them to the hourly budgets, so two ticks
    # that overlap cannot spend the same budget.
    query_cost: int = 1
    # None when the train and score split is off.
    run: ScoringRun | None = None


@frozen
class TeamCensus:
    """The active insights of one eligible team, for the daily per-team census event."""

    team_id: int
    active: int
    active_reasons: dict[str, int]
    active_intervals: dict[str, int]


@frozen
class Selection:
    picks: list[InsightPick]
    # Due insights, picked or not. More than the picks means the tick cap or a budget cut the queue.
    candidates: int
    # Due insights that the walk reached but skipped, because their queries did not fit a budget.
    skipped_for_budget: int = 0
    # Picks of the score pass and of the train pass. With the split off, every pick is a train pass pick.
    picked_score: int = 0
    picked_train: int = 0
    # Score pass picks that score with a model due for a soft retrain.
    scored_stale_model: int = 0
    # Due train candidates that the train pass did not pick: soft ones still score with a stale model, hard ones do not.
    train_backlog_soft: int = 0
    train_backlog_hard: int = 0
    # Active insights of the eligible teams, and how many of them have each reason. One insight can have several.
    active: int = 0
    active_reasons: dict[str, int] = dataclasses.field(default_factory=dict)
    # One entry for each eligible team, also a team with no active insight.
    census: list[TeamCensus] = dataclasses.field(default_factory=list)
    # Teams with active insights whose scored state loaded, and the teams that wait for a later tick.
    teams_planned: int = 0
    teams_skipped: int = 0
    # Eligible teams, and their organizations.
    enrolled_teams: int = 0
    enrolled_organizations: int = 0


@frozen
class ScorePassOrder:
    # Due insights with a current model, longest overdue first.
    order: list[int]
    # Due insights with a model past a soft retrain trigger, longest overdue first.
    stale_order: list[int]
    # Every active insight with a current model, due or not.
    ready: set[int]


@frozen
class QueryBudget:
    """Scoring queries left in this clock hour, for the fleet and for each project."""

    fleet: int
    projects: dict[int, int]


def eligible_teams(config: AnomalyScoringConfig) -> list[Team]:
    """The teams that `config.covers_team` enrolls, in a fixed number of queries, less the teams over their event quota."""
    if not config.enabled:
        return []
    teams = (
        Team.objects.exclude(id__in=config.skip_team_ids)
        .exclude(organization_id__in=config.deny_organization_ids)
        .exclude(id__in=SignalTeamConfig.objects.filter(anomaly_scoring_enabled=False).values("team_id"))
    )
    enrolled: set[int] = set()
    if config.organization_ids:
        listed = teams.filter(organization_id__in=config.organization_ids)
        if config.allow_team_ids:
            listed = listed.filter(id__in=config.allow_team_ids)
        enrolled.update(listed.values_list("id", flat=True))
    if config.self_driving_organization_percentage > 0:
        from products.signals.backend.facade.api import (
            team_ids_with_enabled_source,  # noqa: PLC0415 — the facade imports this module through `search`
        )

        with_source = teams.filter(id__in=team_ids_with_enabled_source()).values_list("id", "organization_id")
        enrolled.update(team_id for team_id, organization_id in with_source if in_rollout(config, organization_id))
    if not enrolled:
        return []
    # Capture drops every event of a project over its event quota, so scoring it wastes the query.
    limited = set(list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY))
    return [team for team in Team.objects.filter(id__in=enrolled) if team.api_token not in limited]


def turned_off_in_settings(team: Team) -> bool:
    """Whether the project turned anomaly scoring off in its self-driving settings. A team without a config row is on."""
    return SignalTeamConfig.objects.filter(team_id=team.id, anomaly_scoring_enabled=False).exists()


def active_insights(
    team_ids: list[int], intervals: tuple[IntervalType, ...], now: datetime.datetime, window_days: int
) -> list[ActiveInsight]:
    """Saved trends insights with a scored interval and at least one activity reason in the last ``window_days``.

    Computed fresh on each call, so an insight drops out once its last reason ages out, and comes back with a new one.
    Its stored state stays, so a later train step picks up where the model left off.
    """
    if not team_ids:
        return []
    since = now - datetime.timedelta(days=window_days)
    reasons_by_id: dict[int, set[ActivityReason]] = {}
    for reason, insight_ids in (
        (ActivityReason.VIEWED, insight_ids_viewed_since(team_ids=team_ids, since=since)),
        (ActivityReason.DASHBOARD_ACCESSED, insight_ids_on_dashboards_accessed_since(team_ids=team_ids, since=since)),
        (ActivityReason.ENABLED_ALERT, enabled_alert_insight_ids(team_ids=team_ids)),
        (ActivityReason.ACTIVE_SUBSCRIPTION, insight_ids_with_active_subscriptions(team_ids=team_ids)),
        (ActivityReason.EDITED, insight_ids_modified_since(team_ids=team_ids, since=since)),
    ):
        for insight_id in insight_ids:
            reasons_by_id.setdefault(insight_id, set()).add(reason)
    return [
        ActiveInsight(
            team_id=insight.team_id,
            insight_id=insight.insight_id,
            interval=IntervalType(insight.interval),
            reasons=frozenset(reasons_by_id[insight.insight_id]),
        )
        for insight in saved_trends_insights(
            team_ids=team_ids,
            insight_ids=list(reasons_by_id),
            intervals=[interval.value for interval in intervals],
            excluded_displays=_UNSCORED_DISPLAYS,
        )
    ]


def reason_counts(insights: Collection[ActiveInsight]) -> dict[str, int]:
    """How many of the insights have each reason, with a zero for a reason none of them has."""
    counts = Counter(reason for insight in insights for reason in insight.reasons)
    return {reason.value: counts[reason] for reason in ActivityReason}


def team_census(team_ids: Collection[int], insights: Collection[ActiveInsight]) -> list[TeamCensus]:
    by_team: dict[int, list[ActiveInsight]] = {team_id: [] for team_id in team_ids}
    for insight in insights:
        by_team.setdefault(insight.team_id, []).append(insight)
    return [
        TeamCensus(
            team_id=team_id,
            active=len(team_insights),
            active_reasons=reason_counts(team_insights),
            active_intervals=dict(Counter(insight.interval.value for insight in team_insights)),
        )
        for team_id, team_insights in sorted(by_team.items())
    ]


def scored_state_since(
    config: AnomalyScoringConfig, interval: IntervalType, now: datetime.datetime
) -> datetime.datetime:
    """How far back the scored state of an insight with this interval reaches: one bucket more than the backfill cap."""
    return now - interval_spec(interval).period * (config.limits.max_backfill_buckets + 1)


def _utc(value: datetime.datetime) -> datetime.datetime:
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)


def _scored_window(insight_ids: Collection[int], since: datetime.datetime) -> ast.Expr:
    return parse_expr(
        "toInt(properties.$anomaly_insight_id) IN {insight_ids} AND timestamp >= {since}",
        placeholders={
            "insight_ids": ast.Tuple(exprs=[ast.Constant(value=insight_id) for insight_id in sorted(insight_ids)]),
            "since": ast.Constant(value=since),
        },
    )


def scored_buckets(
    team: Team, insight_ids_by_since: Mapping[datetime.datetime, Collection[int]], now: datetime.datetime
) -> dict[int, dict[str, datetime.datetime]]:
    """Insight id to the newest scored bucket start of each of its series, for this team's own insights.

    One query reads every window. Each insight reads back only to the ``since`` of its group, so a day or
    week insight does not read the months a month insight needs.

    Any member can capture an event with any properties into the project. Rows for another team's
    insight, or with a future bucket, are ignored, so they cannot stop the scoring of an insight.
    """
    groups = {since: ids for since, ids in sorted(insight_ids_by_since.items()) if ids}
    if not groups:
        return {}
    windows = [_scored_window(ids, since) for since, ids in groups.items()]
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _SCORED_BUCKETS_QUERY,
        team,
        query_type="AnomalyScoresScoredBuckets",
        placeholders={
            "event": ast.Constant(value=SCORE_EVENT),
            "source": ast.Constant(value=SOURCE_INSIGHT),
            "since": ast.Constant(value=min(groups)),
            "now": ast.Constant(value=now),
            "windows": windows[0] if len(windows) == 1 else ast.Or(exprs=windows),
            "limit": ast.Constant(value=_MAX_SCORED_SERIES),
        },
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.DEFAULT,
    )
    state: dict[int, dict[str, datetime.datetime]] = {}
    for insight_id, series_key, newest_bucket in cast(list[tuple[Any, ...]], response.results or []):
        if insight_id is None or not series_key:
            continue
        state.setdefault(int(insight_id), {})[str(series_key)] = _utc(newest_bucket)
    return state


def is_due(
    insight: ActiveInsight, newest_bucket: datetime.datetime | None, timezone: datetime.tzinfo, now: datetime.datetime
) -> bool:
    """The bucket after the newest scored one is complete, and this insight's slot after its end has passed."""
    if newest_bucket is None:
        return True
    next_start = bucket_end(newest_bucket.astimezone(timezone), insight.interval)
    next_end = bucket_end(next_start, insight.interval)
    # The same offset as alert checks, so insights spread over the window after each boundary.
    offset = alert_check_offset(_CALENDAR_INTERVALS[insight.interval], f"anomaly:{insight.insight_id}")
    return now >= next_end + offset


def _cooldown_key(insight_id: int) -> str:
    return f"signals:anomaly_scores:attempted:{insight_id}"


def mark_attempted(insight_id: int, cooldown: datetime.timedelta) -> None:
    cache.set(_cooldown_key(insight_id), True, timeout=int(cooldown.total_seconds()))


def _cooling_down(insight_ids: list[int]) -> set[int]:
    if not insight_ids:
        return set()
    found = cache.get_many([_cooldown_key(insight_id) for insight_id in insight_ids])
    return {insight_id for insight_id in insight_ids if _cooldown_key(insight_id) in found}


def _team_loaded_key(team_id: int) -> str:
    return f"signals:anomaly_scores:team_loaded:{team_id}"


def _team_load_order(team_ids: Collection[int]) -> list[int]:
    """The teams that waited longest since their last scored state load first. A team never loaded goes first."""
    loaded = cache.get_many([_team_loaded_key(team_id) for team_id in team_ids])
    return sorted(team_ids, key=lambda team_id: (loaded.get(_team_loaded_key(team_id), 0.0), team_id))


def _mark_teams_loaded(team_ids: Collection[int], now: datetime.datetime) -> None:
    stamp = _utc(now).timestamp()
    cache.set_many(
        {_team_loaded_key(team_id): stamp for team_id in team_ids}, timeout=int(_TEAM_LOADED_TTL.total_seconds())
    )


def _hour(now: datetime.datetime) -> str:
    return _utc(now).strftime("%Y%m%d%H")


def budget_kind(run: ScoringRun | None) -> ScoringRun:
    """The budgets a pick charges. Only a score step uses the score budgets."""
    return ScoringRun.SCORE if run == ScoringRun.SCORE else ScoringRun.TRAIN


def _budget_prefix(kind: ScoringRun) -> str:
    # Train steps keep the key of the budgets from before the split, so turning the split on keeps the hour's spend.
    return "signals:anomaly_scores:score_queries" if kind == ScoringRun.SCORE else "signals:anomaly_scores:queries"


def _fleet_budget_key(now: datetime.datetime, kind: ScoringRun = ScoringRun.TRAIN) -> str:
    return f"{_budget_prefix(kind)}:{_hour(now)}"


def _project_budget_key(team_id: int, now: datetime.datetime, kind: ScoringRun = ScoringRun.TRAIN) -> str:
    return f"{_budget_prefix(kind)}:{_hour(now)}:team:{team_id}"


def _fleet_cap(config: AnomalyScoringConfig, kind: ScoringRun) -> int:
    return config.max_score_queries_per_hour if kind == ScoringRun.SCORE else config.max_queries_per_hour


def _project_cap(config: AnomalyScoringConfig, kind: ScoringRun) -> int:
    if kind == ScoringRun.SCORE:
        return config.max_score_queries_per_project_per_hour
    return config.max_queries_per_project_per_hour


def remaining_budget(
    config: AnomalyScoringConfig,
    team_ids: Collection[int],
    now: datetime.datetime,
    kind: ScoringRun = ScoringRun.TRAIN,
) -> QueryBudget:
    fleet_key = _fleet_budget_key(now, kind)
    project_keys = {team_id: _project_budget_key(team_id, now, kind) for team_id in team_ids}
    spent = cache.get_many([fleet_key, *project_keys.values()])
    return QueryBudget(
        fleet=_fleet_cap(config, kind) - spent.get(fleet_key, 0),
        projects={team_id: _project_cap(config, kind) - spent.get(key, 0) for team_id, key in project_keys.items()},
    )


def _reserve(key: str, queries: int, cap: int) -> bool:
    # `incr` is atomic, so two planners that run at the same time cannot both take the last queries.
    # `incr` fails on a missing key, and `add` does nothing when the key exists.
    cache.add(key, 0, timeout=int(_BUDGET_TTL.total_seconds()))
    if cache.incr(key, queries) <= cap:
        return True
    cache.decr(key, queries)
    return False


def reserve_queries(
    config: AnomalyScoringConfig,
    team_id: int,
    queries: int,
    now: datetime.datetime,
    kind: ScoringRun = ScoringRun.TRAIN,
) -> bool:
    """Charge ``queries`` to both hourly budgets of ``kind``, or to neither when one of them has too few left."""
    fleet_key = _fleet_budget_key(now, kind)
    if not _reserve(fleet_key, queries, _fleet_cap(config, kind)):
        return False
    if _reserve(_project_budget_key(team_id, now, kind), queries, _project_cap(config, kind)):
        return True
    cache.decr(fleet_key, queries)
    return False


def within_budget(
    order: list[int],
    team_ids: dict[int, int],
    budgets: dict[ScoringRun, QueryBudget],
    limit: int,
    plans_for: Callable[[list[int]], dict[int, RunPlan]],
    reserve: Callable[[int, RunPlan], bool],
) -> tuple[dict[int, RunPlan], int]:
    """The insights of ``order`` whose cost fits both budgets of their kind, up to ``limit``, and the skip count.

    A pick that does not fit is skipped and the walk continues, so a large insight does not block smaller ones.
    A pick of a kind with no entry in ``budgets`` belongs to the other pass, and the walk passes over it.
    ``budgets`` are snapshots that skip most misses without a cache call. ``reserve`` charges a pick for real.
    ``plans_for`` loads plans in batches of ``limit``, and only for insights that a snapshot can still fit.
    """
    fleets = {kind: budget.fleet for kind, budget in budgets.items()}
    projects = {kind: dict(budget.projects) for kind, budget in budgets.items()}
    picked: dict[int, RunPlan] = {}
    skipped = 0
    batch_size = max(1, limit)
    for start in range(0, len(order), batch_size):
        if len(picked) >= limit:
            break
        batch = order[start : start + batch_size]
        affordable = [
            insight_id
            for insight_id in batch
            if any(fleets[kind] > 0 and projects[kind].get(team_ids[insight_id], 0) > 0 for kind in budgets)
        ]
        plans = plans_for(affordable) if affordable else {}
        for insight_id in batch:
            if len(picked) >= limit:
                break
            team_id = team_ids[insight_id]
            plan = plans.get(insight_id)
            kind = budget_kind(plan.run if plan else None)
            if plan is not None and kind not in budgets:
                continue
            if (
                plan is None
                or plan.queries > fleets[kind]
                or plan.queries > projects[kind].get(team_id, 0)
                or not reserve(team_id, plan)
            ):
                skipped += 1
                continue
            picked[insight_id] = plan
            fleets[kind] -= plan.queries
            projects[kind][team_id] -= plan.queries
    return picked, skipped


def _run_plans(
    team: Team, insight_ids: list[int], config: AnomalyScoringConfig, now: datetime.datetime
) -> dict[int, RunPlan]:
    insights = insights_including_soft_deleted_for_team(team_id=team.id, insight_ids=insight_ids)
    states = load_states(team, insights) if config.train_score_split else {}
    plans = {insight.id: plan_run(insight, team, states.get(insight.id), config, now) for insight in insights}
    # An insight that no longer exists sends no query, but one query is the safe charge.
    missing = RunPlan(queries=1, run=ScoringRun.TRAIN if config.train_score_split else None)
    return {insight_id: plans.get(insight_id, missing) for insight_id in insight_ids}


def _take_turns(team_orders: list[list[int]]) -> list[int]:
    # Projects take turns, so one large project cannot take every slot of the tick budget.
    return [insight_id for turn in itertools.zip_longest(*team_orders) for insight_id in turn if insight_id is not None]


def load_scored_state(
    config: AnomalyScoringConfig,
    teams: dict[int, Team],
    insights: Collection[ActiveInsight],
    now: datetime.datetime,
    deadline: float | None,
) -> tuple[dict[int, dict[str, datetime.datetime]], set[int]]:
    """The scored state of the insights, and the teams whose state loaded.

    One query per team. The teams that waited longest load first. Loading stops at ``deadline``, a
    ``time.monotonic`` value, after at least one team, or when ClickHouse is full for several teams.
    A team whose query fails waits for a later tick.
    """
    windows: dict[int, dict[datetime.datetime, set[int]]] = {}
    for insight in insights:
        since = scored_state_since(config, insight.interval, now)
        windows.setdefault(insight.team_id, {}).setdefault(since, set()).add(insight.insight_id)
    state: dict[int, dict[str, datetime.datetime]] = {}
    loaded: set[int] = set()
    attempted: list[int] = []
    at_capacity = 0
    for team_id in _team_load_order(windows):
        if at_capacity >= _MAX_AT_CAPACITY_TEAMS or (
            attempted and deadline is not None and time.monotonic() >= deadline
        ):
            break
        attempted.append(team_id)
        try:
            state.update(scored_buckets(teams[team_id], windows[team_id], now))
        except _SCORED_BUCKETS_LIMIT_ERRORS as error:
            logger.warning("anomaly_scoring_scored_buckets_failed", team_id=team_id, error_class=type(error).__name__)
            if isinstance(error, ClickHouseAtCapacity):
                at_capacity += 1
            continue
        loaded.add(team_id)
    # A failed team also goes to the back, so a team whose query always fails does not take time from every plan.
    _mark_teams_loaded(attempted, now)
    if len(attempted) < len(windows):
        logger.info(
            "anomaly_scoring_plan_stopped_loading",
            teams_loaded=len(loaded),
            teams_skipped=len(windows) - len(loaded),
            at_capacity=at_capacity,
        )
    return state, loaded


def select_insights(
    config: AnomalyScoringConfig,
    selection_config: SelectionConfig,
    now: datetime.datetime,
    limit: int | None = None,
    deadline: float | None = None,
) -> Selection:
    """The picks of the tick. ``limit`` replaces the pick cap of each pass, for a manual run.

    ``deadline`` is a ``time.monotonic`` value. After it, no more teams load, and the plan uses the teams it has.
    """
    teams = {team.id: team for team in eligible_teams(config)}
    insights = active_insights(list(teams), config.intervals, now, config.active_window_days)
    active = len(insights)
    active_reasons = reason_counts(insights)
    census = team_census(teams, insights)
    teams_with_insights = {insight.team_id for insight in insights}
    state, loaded_teams = load_scored_state(config, teams, insights, now, deadline)
    # Without its scored state, every insight of the team looks never scored, so the team waits for a later tick.
    insights = [insight for insight in insights if insight.team_id in loaded_teams]

    newest_buckets = {
        insight.insight_id: max(state[insight.insight_id].values()) if insight.insight_id in state else None
        for insight in insights
    }
    cooling = _cooling_down([insight.insight_id for insight in insights])
    active_by_id = {insight.insight_id: insight for insight in insights if insight.insight_id not in cooling}
    team_ids = {insight_id: insight.team_id for insight_id, insight in active_by_id.items()}

    # Both passes share the plans, so an insight that the score pass planned is not planned again.
    planned: dict[int, RunPlan] = {}

    def plans_for(insight_ids: list[int]) -> dict[int, RunPlan]:
        missing = [insight_id for insight_id in insight_ids if insight_id not in planned]
        for team_id in sorted({team_ids[insight_id] for insight_id in missing}):
            team_batch = [insight_id for insight_id in missing if team_ids[insight_id] == team_id]
            planned.update(_run_plans(teams[team_id], team_batch, config, now))
        return {insight_id: planned[insight_id] for insight_id in insight_ids}

    def walk(
        order: list[int],
        kind: ScoringRun,
        cap: int,
        plans: Callable[[list[int]], dict[int, RunPlan]] = plans_for,
    ) -> tuple[dict[int, RunPlan], int]:
        # Read the budget before any cost, so a spent hour loads no insight.
        return within_budget(
            order,
            team_ids,
            {kind: remaining_budget(config, {team_ids[insight_id] for insight_id in order}, now, kind)},
            cap,
            plans,
            reserve=lambda team_id, plan: reserve_queries(config, team_id, plan.queries, now, budget_kind(plan.run)),
        )

    score_order_ids: list[int] = []
    stale_order_ids: list[int] = []
    score_ready: set[int] = set()
    score_picked: dict[int, RunPlan] = {}
    score_skipped = 0
    score_cap = config.max_score_insights_per_tick if limit is None else limit
    if config.train_score_split:
        score_pass = _score_order(active_by_id, teams, config, now)
        score_order_ids, stale_order_ids, score_ready = score_pass.order, score_pass.stale_order, score_pass.ready
        score_picked, score_skipped = walk(score_order_ids, ScoringRun.SCORE, score_cap)
        # A spent score budget makes the walk load no plan. Plan the head of the order anyway, so that an
        # edited insight there still reaches the train pass while the train budget has room.
        plans_for(score_order_ids[:score_cap])
    # A score-ready insight belongs to the score pass, also when its cap or budget left it out this tick.
    # Without this, the train pass loads a plan for every one of them and then passes over it. An insight
    # that the score pass planned as a train step, for example after an edit, goes to the train pass.
    # A stale model goes to the train pass first, and the score pass takes it back below.
    score_only = {
        insight_id
        for insight_id in score_ready
        if insight_id not in planned or planned[insight_id].run == ScoringRun.SCORE
    }

    due_by_id = {
        insight_id: insight
        for insight_id, insight in active_by_id.items()
        if insight_id not in score_picked
        and insight_id not in score_only
        and is_due(insight, newest_buckets[insight_id], teams[insight.team_id].timezone_info, now)
    }
    usage: dict[int, InsightUsage] = {}
    for team_id in sorted({insight.team_id for insight in due_by_id.values()}):
        due_ids = [insight.insight_id for insight in due_by_id.values() if insight.team_id == team_id]
        usage.update(insight_usage(team_id=team_id, insight_ids=due_ids, now=now))
    candidates_by_team: dict[int, list[Candidate]] = {}
    for insight in due_by_id.values():
        newest = newest_buckets[insight.insight_id]
        candidates_by_team.setdefault(insight.team_id, []).append(
            Candidate(
                insight_id=insight.insight_id,
                interval=insight.interval,
                # Staleness steps whole buckets, so it needs the bucket start in the project timezone.
                newest_scored_bucket=None
                if newest is None
                else newest.astimezone(teams[insight.team_id].timezone_info),
                usage=usage[insight.insight_id],
            )
        )
    train_order = _take_turns(
        [
            pick_order(
                candidates_by_team[team_id],
                config=selection_config,
                tick_start=now,
                max_staleness=config.limits.max_backfill_buckets,
            )
            for team_id in sorted(candidates_by_team)
        ]
    )
    if config.train_score_split:
        train_cap = config.max_train_insights_per_tick
    else:
        train_cap = config.max_insights_per_tick
    # A stale model plans as a train step here. With the split off, every pick charges the train budgets.
    train_picked, train_skipped = walk(train_order, ScoringRun.TRAIN, train_cap if limit is None else limit)

    stale_picked: dict[int, RunPlan] = {}
    stale_skipped = 0
    stale_cap = score_cap - len(score_picked)
    if config.train_score_split and stale_cap > 0:
        stale_picked, stale_skipped = walk(
            [insight_id for insight_id in stale_order_ids if insight_id not in train_picked],
            ScoringRun.SCORE,
            stale_cap,
            lambda insight_ids: {
                insight_id: _as_score_step(plan) for insight_id, plan in plans_for(insight_ids).items()
            },
        )
    score_picked.update(stale_picked)

    stale_ready = set(stale_order_ids)
    backlog = [insight_id for insight_id in due_by_id if insight_id not in train_picked]
    picks = [
        InsightPick(
            team_id=team_ids[insight_id],
            insight_id=insight_id,
            scored_through=state.get(insight_id, {}),
            interval=active_by_id[insight_id].interval,
            query_cost=plan.queries,
            run=plan.run,
        )
        for insight_id, plan in [*score_picked.items(), *train_picked.items()]
    ]
    return Selection(
        picks=picks,
        candidates=len({*score_order_ids, *stale_order_ids, *train_order}),
        skipped_for_budget=score_skipped + train_skipped + stale_skipped,
        picked_score=len(score_picked),
        picked_train=len(train_picked),
        scored_stale_model=len(stale_picked),
        train_backlog_soft=sum(insight_id in stale_ready for insight_id in backlog),
        train_backlog_hard=sum(insight_id not in stale_ready for insight_id in backlog),
        active=active,
        active_reasons=active_reasons,
        census=census,
        teams_planned=len(loaded_teams),
        teams_skipped=len(teams_with_insights) - len(loaded_teams),
        enrolled_teams=len(teams),
        enrolled_organizations=len({team.organization_id for team in teams.values()}),
    )


def _as_score_step(plan: RunPlan) -> RunPlan:
    """A stale model plan as a score step. A plan that needs a train step stays one, and the score pass passes over it."""
    return dataclasses.replace(plan, run=ScoringRun.SCORE) if plan.stale_model else plan


def _score_order(
    active_by_id: dict[int, ActiveInsight],
    teams: dict[int, Team],
    config: AnomalyScoringConfig,
    now: datetime.datetime,
) -> ScorePassOrder:
    """The score pass orders, longest overdue first in each project.

    A stale model is in `stale_order` only, because the train pass gets it first. `ready` leaves out the
    stale models, so they reach the train pass.
    """
    team_orders: list[list[int]] = []
    stale_orders: list[list[int]] = []
    ready: set[int] = set()
    for team_id in sorted({insight.team_id for insight in active_by_id.values()}):
        team = teams[team_id]
        team_insights = [insight for insight in active_by_id.values() if insight.team_id == team_id]
        scored = score_ready_by_insight(team, [insight.insight_id for insight in team_insights], config, now)
        ready.update(insight_id for insight_id, state in scored.items() if not state.stale_model)
        candidates = [
            (
                scored[insight.insight_id].stale_model,
                ScoreCandidate(
                    insight_id=insight.insight_id,
                    interval=insight.interval,
                    scored_through=scored[insight.insight_id].scored_through.astimezone(team.timezone_info),
                ),
            )
            for insight in team_insights
            if insight.insight_id in scored
            and is_due(insight, scored[insight.insight_id].scored_through, team.timezone_info, now)
        ]
        for stale, orders in ((False, team_orders), (True, stale_orders)):
            orders.append(
                score_order(
                    [candidate for is_stale, candidate in candidates if is_stale == stale],
                    now=now,
                    max_staleness=config.limits.max_backfill_buckets,
                )
            )
    return ScorePassOrder(order=_take_turns(team_orders), stale_order=_take_turns(stale_orders), ready=ready)
