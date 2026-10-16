from collections.abc import Sequence
from datetime import date, timedelta
from functools import partial

from django.utils import timezone

from posthog.models import FileSystemViewLog

from products.product_analytics.backend.facade.api import get_insight_series

from ...facade import contracts
from ...facade.enums import HighlightInterval, HighlightUnit
from ..highlight_rules import pretty, short, usable_series
from ..highlight_trends import complete, detect
from ..highlight_types import Context, Found, Source

ROUTINE_WINDOW_DAYS = 28
DAILY_ROUTINE_DAYS = 8
WEEKLY_ROUTINE_WEEKS = 3
ROUTINE_CANDIDATES = 6
ROUTINE_TILES = 2


def find(context: Context) -> Found:
    metrics: list[contracts.HighlightMetric] = []
    for short_id in _routine_insights(context):
        metric = context.guard(f"routine {short_id}", partial(_metric, context, short_id), None)
        if metric is not None:
            metrics.append(metric)
        if len(metrics) == ROUTINE_TILES:
            break
    return Found(pulse=tuple(metrics))


def routine_days(view_days: Sequence[date], today: date) -> int:
    recent = {day for day in view_days if today - timedelta(days=ROUTINE_WINDOW_DAYS) < day <= today}
    daily = sum(1 for day in recent if day > today - timedelta(days=14)) >= DAILY_ROUTINE_DAYS
    weekly = len({day.isocalendar()[:2] for day in recent}) >= WEEKLY_ROUTINE_WEEKS
    return len(recent) if daily or weekly else 0


def _routine_insights(context: Context) -> list[str]:
    views = FileSystemViewLog.objects.filter(
        team=context.team,
        user=context.user,
        type="insight",
        viewed_at__gte=timezone.now() - timedelta(days=ROUTINE_WINDOW_DAYS),
    ).values_list("ref", "view_days", "viewed_at")
    ranked = sorted(
        ((routine_days(days or [], context.today), viewed_at, ref) for ref, days, viewed_at in views), reverse=True
    )
    return [ref for days, _viewed_at, ref in ranked if days][:ROUTINE_CANDIDATES]


def _metric(context: Context, short_id: str) -> contracts.HighlightMetric | None:
    insight = get_insight_series(team=context.team, user=context.user, short_id=short_id)
    if insight is None:
        return None
    series = usable_series(insight, context.today)
    if not series:
        return None
    name, points = max(series.items(), key=lambda item: sum(abs(v) for _, v in item[1]))
    period = insight.period
    _, values = detect(points, period, context.today, period == "day" and name in insight.averaged_series)
    if len(values) < 2:
        return None
    if period == "day":
        by_day = dict(complete(points, "day", context.today))
        line = [by_day.get(context.today - timedelta(days=offset), 0.0) for offset in range(28, 0, -1)]
    else:
        line = values[-12:]
    value_format = (
        contracts.HighlightValueFormat(
            format=insight.value_format,
            prefix=insight.value_prefix,
            postfix=insight.value_postfix,
            decimal_places=insight.decimal_places,
        )
        if insight.value_format not in (None, "numeric")
        or insight.value_prefix
        or insight.value_postfix
        or insight.decimal_places is not None
        else None
    )
    return contracts.HighlightMetric(
        key=f"insight:{short_id}",
        name=short(insight.name or pretty(name), 40),
        value=values[-1],
        unit=HighlightUnit.NUMBER,
        change_pct=round((values[-1] / values[-2] - 1) * 100, 1) if values[-2] else None,
        series=line,
        interval=HighlightInterval(period),
        url=f"/insights/{short_id}",
        value_format=value_format,
    )


SOURCE = Source(name="routine", find=find, scopes=("insight:read",), pulse_order=1)
