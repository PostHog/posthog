from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from posthog.schema import CompareFilter, DateRange, WebGoalsQuery, WebOverviewQuery

from posthog.models.team.team import Team
from posthog.models.user import User

from products.web_analytics.backend.achievements.definitions import STREAK_ARM_WEEKLY
from products.web_analytics.backend.hogql_queries.web_goals import NoActionsError, WebGoalsQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
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


def evaluate_cumulative_pageviews(ctx: EvalContext) -> int:
    total = 0
    for team in _project_environment_teams(ctx.team):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="all"),
            compareFilter=CompareFilter(compare=False),
            filterTestAccounts=True,
            properties=[],
        )
        response = WebOverviewQueryRunner(team=team, query=query).calculate()
        for item in response.results or []:
            if item.key == "views":
                total += int(item.value or 0)
                break
    return total


def _first_value(value: object) -> Any:
    return value[0] if isinstance(value, list | tuple) else value


def evaluate_conversions(ctx: EvalContext) -> int:
    """Single monotone value spanning both Goal Hog mechanics: stages 1-3 count configured goals,
    stages 4-5 require a single goal to reach 100 / 1,000 conversions. `max(goals, best goal)` maps
    cleanly onto the (1, 3, 5, 100, 1000) thresholds. Aggregated across the project's environments:
    goal counts sum, best-goal conversions take the project-wide max."""
    num_goals = 0
    best_goal_conversions = 0
    for team in _project_environment_teams(ctx.team):
        query = WebGoalsQuery(
            dateRange=DateRange(date_from="all"),
            compareFilter=CompareFilter(compare=False),
            properties=[],
        )
        try:
            response = WebGoalsQueryRunner(team=team, query=query).calculate()
        except NoActionsError:
            continue
        results = response.results or []
        num_goals += len(results)
        for row in results:
            best_goal_conversions = max(best_goal_conversions, int(_first_value(row[2]) or 0))
    return max(num_goals, best_goal_conversions)


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
