from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.actions.backend.models.action import Action
from products.web_analytics.backend.achievements.definitions import STREAK_ARM_WEEKLY
from products.web_analytics.backend.achievements.query_concurrency import get_achievement_query_limiter
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import test_account_filter_expr
from products.web_analytics.backend.models import WebAnalyticsInteraction, WebAnalyticsVisit


@dataclass(frozen=True)
class EvalContext:
    team: Team
    user: User | None
    today: date
    arm: str | None


@frozen
class PriorProgress:
    value: int
    last_computed_at: datetime | None
    checkpoint: dict[str, object]


@frozen
class TrackEvaluation:
    value: int
    checkpoint: dict[str, object] | None = None


def _week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _consecutive_days_with_grace(visit_dates: set[date], today: date) -> int:
    """Consecutive visited days ending at today, allowing a single 1-day grace gap. Today not yet
    visited keeps the streak alive (the day isn't over); a 2-day gap breaks it."""
    streak = 0
    grace_used = False
    cursor = today if today in visit_dates else today - timedelta(days=1)
    while True:
        if cursor in visit_dates:
            streak += 1
            cursor -= timedelta(days=1)
        elif not grace_used:
            grace_used = True
            cursor -= timedelta(days=1)
        else:
            break
    return streak


def _consecutive_weeks(visit_dates: set[date], today: date) -> int:
    visited_mondays = {_week_monday(day) for day in visit_dates}
    streak = 0
    cursor = _week_monday(today)
    if cursor not in visited_mondays:
        cursor -= timedelta(days=7)
    while cursor in visited_mondays:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def evaluate_streak(ctx: EvalContext) -> int:
    if ctx.user is None:
        return 0
    window_start = ctx.today - timedelta(days=90)
    visit_dates = set(
        WebAnalyticsVisit.objects.for_team(ctx.team.id)
        .filter(user_id=ctx.user.id, visit_date__gte=window_start)
        .values_list("visit_date", flat=True)
    )
    if not visit_dates:
        return 0
    if ctx.arm == STREAK_ARM_WEEKLY:
        return _consecutive_weeks(visit_dates, ctx.today)
    return _consecutive_days_with_grace(visit_dates, ctx.today)


def evaluate_loyal_days(ctx: EvalContext) -> int:
    if ctx.user is None:
        return 0
    return (
        WebAnalyticsVisit.objects.for_team(ctx.team.id)
        .filter(user_id=ctx.user.id)
        .values("visit_date")
        .distinct()
        .count()
    )


def _project_environment_teams(team: Team) -> list[Team]:
    """Every environment team of the project. Web traffic is stored per-environment (team_id), so a
    team-scoped total must aggregate across all environments, not just the canonical team — otherwise
    a project whose traffic lives in a child environment never progresses. N environments → N query
    runner executions; projects rarely have more than one or two."""
    return list(Team.objects.filter(project_id=team.project_id))


def _test_account_filter_expr(team: Team) -> ast.Expr:
    filters = team.test_account_filters if isinstance(team.test_account_filters, list) else []
    return test_account_filter_expr(test_account_filters=filters, team=team)


INGESTION_LAG = timedelta(hours=1)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _time_window_expr(since: datetime | None, until: datetime) -> ast.Expr:
    before_until = ast.CompareOperation(
        op=ast.CompareOperationOp.Lt, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=until)
    )
    if since is None:
        return before_until
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=since)
            ),
            before_until,
        ]
    )


def evaluate_cumulative_pageviews(ctx: EvalContext, prior: PriorProgress) -> TrackEvaluation:
    until = timezone.now() - INGESTION_LAG
    since = _parse_timestamp(prior.checkpoint.get("counted_through")) or prior.last_computed_at
    total = prior.value if since is not None else 0
    with (
        tags_context(product=Product.WEB_ANALYTICS, feature=Feature.ENRICHMENT),
        get_achievement_query_limiter().run(team_id=ctx.team.id),
    ):
        for team in _project_environment_teams(ctx.team):
            query = parse_select(
                "SELECT count() FROM events WHERE and(event IN ('$pageview', '$screen'), {window}, {test})",
                placeholders={"window": _time_window_expr(since, until), "test": _test_account_filter_expr(team)},
            )
            response = execute_hogql_query(query=query, team=team, query_type="web_achievements_pageviews")
            if response.results:
                total += int(response.results[0][0] or 0)
    return TrackEvaluation(value=total, checkpoint={"counted_through": until.isoformat()})


CONVERSIONS_LOOKBACK_DAYS = 90


def _action_event_filter_expr(actions: list[Action]) -> ast.Expr:
    event_names: set[str] = set()
    for action in actions:
        step_events = action.get_step_events()
        if not step_events or any(event is None for event in step_events):
            return ast.Constant(value=True)
        event_names.update(event for event in step_events if event is not None)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=name) for name in sorted(event_names)]),
    )


def _daily_buckets(checkpoint: dict[str, object], action_ids: list[int]) -> dict[str, list[int]] | None:
    daily = checkpoint.get("daily")
    if checkpoint.get("action_ids") != action_ids or not isinstance(daily, dict):
        return None
    try:
        return {
            str(day): [int(count) for count in counts]
            for day, counts in daily.items()
            if isinstance(counts, list) and len(counts) == len(action_ids)
        }
    except (TypeError, ValueError):
        return None


def evaluate_conversions(ctx: EvalContext, prior: PriorProgress) -> TrackEvaluation:
    actions = list(
        Action.objects.filter(team__project_id=ctx.team.project_id, deleted=False).order_by(
            "pinned_at", "-last_calculated_at"
        )[:5]
    )
    if not actions:
        return TrackEvaluation(value=0, checkpoint={})

    until = timezone.now() - INGESTION_LAG
    window_start = until - timedelta(days=CONVERSIONS_LOOKBACK_DAYS)
    action_ids = [action.id for action in actions]
    daily = _daily_buckets(prior.checkpoint, action_ids)
    counted_through = _parse_timestamp(prior.checkpoint.get("counted_through"))
    if daily is None or counted_through is None:
        daily, since = {}, window_start
    else:
        since = max(counted_through.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0), window_start)

    rescanned: dict[str, list[int]] = {}
    with (
        tags_context(product=Product.WEB_ANALYTICS, feature=Feature.ENRICHMENT),
        get_achievement_query_limiter().run(team_id=ctx.team.id),
    ):
        for team in _project_environment_teams(ctx.team):
            query = parse_select(
                "SELECT toDate(toTimeZone(timestamp, 'UTC')) AS day FROM events WHERE and({window}, {events}, {test}) GROUP BY day",
                placeholders={
                    "window": _time_window_expr(since, until),
                    "events": _action_event_filter_expr(actions),
                    "test": _test_account_filter_expr(team),
                },
            )
            if not isinstance(query, ast.SelectQuery):
                raise TypeError(f"evaluate_conversions: expected SelectQuery, got {type(query)}")
            query.select = [
                query.select[0],
                *(ast.Call(name="countIf", args=[action_to_expr(action)]) for action in actions),
            ]
            response = execute_hogql_query(query=query, team=team, query_type="web_achievements_conversions")
            for row in response.results or []:
                day_counts = rescanned.setdefault(row[0].isoformat(), [0] * len(actions))
                for index, value in enumerate(row[1:]):
                    day_counts[index] += int(value or 0)

    oldest_kept_day = window_start.date().isoformat()
    daily = {day: counts for day, counts in {**daily, **rescanned}.items() if day >= oldest_kept_day}
    per_action_totals = [sum(counts[index] for counts in daily.values()) for index in range(len(actions))]
    return TrackEvaluation(
        value=max(len(actions), max(per_action_totals, default=0)),
        checkpoint={"action_ids": action_ids, "daily": daily, "counted_through": until.isoformat()},
    )


def _interaction_count(ctx: EvalContext, kind: str) -> int:
    if ctx.user is None:
        return 0
    row = WebAnalyticsInteraction.objects.for_team(ctx.team.id).filter(user_id=ctx.user.id, kind=kind).first()
    return row.count if row else 0


def evaluate_data_events(ctx: EvalContext) -> int:
    return _interaction_count(ctx, WebAnalyticsInteraction.DATA)


def evaluate_recordings_opened(ctx: EvalContext) -> int:
    return _interaction_count(ctx, WebAnalyticsInteraction.RECORDING)


EVALUATORS: dict[str, Callable[[EvalContext], int]] = {
    "streak": evaluate_streak,
    "loyal_days": evaluate_loyal_days,
    "data_events": evaluate_data_events,
    "recordings_opened": evaluate_recordings_opened,
}

INCREMENTAL_EVALUATORS: dict[str, Callable[[EvalContext, PriorProgress], TrackEvaluation]] = {
    "cumulative_pageviews": evaluate_cumulative_pageviews,
    "conversions": evaluate_conversions,
}
