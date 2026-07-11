from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models.team.team import Team
from posthog.models.user import User

from products.actions.backend.models.action import Action
from products.web_analytics.backend.achievements.definitions import STREAK_ARM_WEEKLY
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import test_account_filter_expr
from products.web_analytics.backend.models import WebAnalyticsInteraction, WebAnalyticsVisit


@dataclass(frozen=True)
class EvalContext:
    team: Team
    user: User | None
    today: date
    arm: str | None


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


def _count_pageviews_window(ctx: EvalContext, since: datetime | None, until: datetime | None) -> int:
    """Count `$pageview`/`$screen` across all of the project's environment teams. `since`/`until`
    bound the query to a timestamp window so ClickHouse prunes partitions instead of scanning all of
    history — an unbounded scan fanned out across every active team exhausts the shared query pool.
    Both `None` counts all history (used only for the one-time backfill seed)."""
    total = 0
    for team in _project_environment_teams(ctx.team):
        clauses = ["event IN ('$pageview', '$screen')", "{test}"]
        placeholders: dict[str, ast.Expr] = {"test": _test_account_filter_expr(team)}
        if since is not None:
            clauses.append("timestamp > {since}")
            placeholders["since"] = ast.Constant(value=since)
        if until is not None:
            clauses.append("timestamp <= {until}")
            placeholders["until"] = ast.Constant(value=until)
        query = parse_select(
            f"SELECT count() FROM events WHERE and({', '.join(clauses)})",
            placeholders=placeholders,
        )
        response = execute_hogql_query(
            query=query, team=team, query_type="web_achievements_pageviews", workload=Workload.OFFLINE
        )
        if response.results:
            total += int(response.results[0][0] or 0)
    return total


def count_cumulative_pageviews_since(ctx: EvalContext, since: datetime, until: datetime) -> int:
    """Pageviews in the half-open window `(since, until]` — the incremental delta the periodic sweep
    adds to a team's running total."""
    return _count_pageviews_window(ctx, since, until)


def evaluate_cumulative_pageviews(ctx: EvalContext) -> int:
    """Full all-history pageview count. Used only by the manual per-team backfill seed; the periodic
    recompute accumulates bounded deltas via `count_cumulative_pageviews_since` instead."""
    return _count_pageviews_window(ctx, None, None)


CONVERSIONS_LOOKBACK_DAYS = 90


def evaluate_conversions(ctx: EvalContext) -> int:
    actions = list(
        Action.objects.filter(team__project_id=ctx.team.project_id, deleted=False).order_by(
            "pinned_at", "-last_calculated_at"
        )[:5]
    )
    if not actions:
        return 0

    per_action_totals = [0] * len(actions)
    for team in _project_environment_teams(ctx.team):
        query = parse_select(
            "SELECT 1 FROM events WHERE and(timestamp >= now() - toIntervalDay({days}), {test})",
            placeholders={
                "days": ast.Constant(value=CONVERSIONS_LOOKBACK_DAYS),
                "test": _test_account_filter_expr(team),
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise TypeError(f"evaluate_conversions: expected SelectQuery, got {type(query)}")
        query.select = [ast.Call(name="countIf", args=[action_to_expr(action)]) for action in actions]
        response = execute_hogql_query(
            query=query, team=team, query_type="web_achievements_conversions", workload=Workload.OFFLINE
        )
        if response.results:
            for index, value in enumerate(response.results[0]):
                per_action_totals[index] += int(value or 0)

    return max(len(actions), max(per_action_totals, default=0))


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
    "cumulative_pageviews": evaluate_cumulative_pageviews,
    "conversions": evaluate_conversions,
    "data_events": evaluate_data_events,
    "recordings_opened": evaluate_recordings_opened,
}
