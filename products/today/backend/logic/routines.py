from collections.abc import Sequence
from datetime import date, timedelta

from django.utils import timezone

from posthog.models import FileSystemViewLog

from ..facade.contracts import HighlightContext

ROUTINE_WINDOW_DAYS = 28
DAILY_ROUTINE_DAYS = 8
WARMUP_ROUTINE_DAYS = 2
WARMUP_HISTORY_DAYS = 14
VIEW_DAYS_RECORDED_SINCE = date(2026, 10, 16)
WEEKLY_ROUTINE_WEEKS = 3


def routine_days(view_days: Sequence[date], today: date, warming_up: bool = False) -> int:
    recent = {day for day in view_days if today - timedelta(days=ROUTINE_WINDOW_DAYS) < day <= today}
    needed = WARMUP_ROUTINE_DAYS if warming_up else DAILY_ROUTINE_DAYS
    daily = sum(1 for day in recent if day > today - timedelta(days=14)) >= needed
    weekly = len({day.isocalendar()[:2] for day in recent}) >= WEEKLY_ROUTINE_WEEKS
    return len(recent) if daily or weekly else 0


def is_warming_up(today: date) -> bool:
    """Whether view days have been recorded for too short a time for the daily rule."""
    return (today - VIEW_DAYS_RECORDED_SINCE).days < WARMUP_HISTORY_DAYS


def viewed_days(context: HighlightContext, kind: str, refs: Sequence[str] | None = None) -> dict[str, frozenset[date]]:
    """The days on which the viewer opened each item of this kind in the routine window, keyed by ref."""
    views = FileSystemViewLog.objects.filter(
        team=context.team,
        user=context.user,
        type=kind,
        viewed_at__gte=timezone.now() - timedelta(days=ROUTINE_WINDOW_DAYS),
    )
    if refs is not None:
        views = views.filter(ref__in=refs)
    return {ref: frozenset(days or []) for ref, days in views.values_list("ref", "view_days")}


def routine_days_for(context: HighlightContext, kind: str, *refs: str) -> int:
    """How many days the viewer opened any of these items in the routine window, or 0 when that is no routine.

    Scenes are items too: `routine_days_for(context, "scene", "Replay")` tells whether the viewer opens Replay often.
    """
    opened = set().union(*viewed_days(context, kind, refs).values())
    return routine_days(sorted(opened), context.today, is_warming_up(context.today))
