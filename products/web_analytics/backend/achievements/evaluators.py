from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from posthog.models.team.team import Team
from posthog.models.user import User

from products.web_analytics.backend.achievements.definitions import STREAK_ARM_WEEKLY
from products.web_analytics.backend.models import WebAnalyticsInteraction, WebAnalyticsVisit


@dataclass(frozen=True)
class EvalContext:
    team: Team
    user: User
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
    return (
        WebAnalyticsVisit.objects.for_team(ctx.team.id)
        .filter(user_id=ctx.user.id)
        .values("visit_date")
        .distinct()
        .count()
    )


def _interaction_count(ctx: EvalContext, kind: str) -> int:
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
