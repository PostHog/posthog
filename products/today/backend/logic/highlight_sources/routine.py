from collections.abc import Collection, Sequence
from datetime import date, timedelta
from functools import partial

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import FileSystemViewLog
from posthog.models.file_system.file_system_view_log import VIEW_DAYS_KEPT

from products.dashboards.backend.facade.api import (
    DashboardInsights,
    DashboardInsightTile,
    dashboard_insight_tile,
    dashboard_insights,
)
from products.product_analytics.backend.facade.api import get_insight_series
from products.product_analytics.backend.facade.contracts import InsightDashboardContext

from ...facade import contracts
from ...facade.enums import HighlightInterval, HighlightMetricReason, HighlightUnit
from ...feature_flags import FRECENCY_RANKING, RECENCY_RANKING, pulse_ranking
from ..highlight_rules import short
from ..highlight_series import pretty, usable_series
from ..highlight_trends import complete, detect
from ..highlight_types import Context, Found, Source

ROUTINE_WINDOW_DAYS = 28
DAILY_ROUTINE_DAYS = 8
WARMUP_ROUTINE_DAYS = 2
WARMUP_HISTORY_DAYS = 14
VIEW_DAYS_RECORDED_SINCE = date(2026, 10, 16)
WEEKLY_ROUTINE_WEEKS = 3
ROUTINE_CANDIDATES = 6
ROUTINE_TILES = 2
FRECENCY_HALF_LIFE_DAYS = 14
FRECENCY_LOOKBACK_DAYS = VIEW_DAYS_KEPT
FRECENCY_CANDIDATES = 8
FRECENCY_TILES = 4
DASHBOARD_TILES_TRIED = 6
OPENED_DAYS_WINDOW = 14
MOVERS_SHOWN = 4


@frozen
class ViewedItem:
    kind: str
    ref: str
    days: frozenset[date]


def find(context: Context) -> Found:
    pinned = context.pinned
    budget = FRECENCY_TILES - len(pinned)
    ranking = pulse_ranking(context.user, context.team)
    if ranking in (FRECENCY_RANKING, RECENCY_RANKING):
        return Found(pulse=tuple(_frecent_metrics(context, ranking, pinned, budget)))
    metrics: list[contracts.HighlightMetric] = []
    for item in _routine_insights(context):
        if len(metrics) >= min(ROUTINE_TILES, budget):
            break
        if f"insight:{item.ref}" in pinned:
            continue
        metric = context.guard(f"routine {item.ref}", partial(insight_metric, context, item.ref, viewed=item), None)
        if metric is not None:
            metrics.append(metric)
    return Found(pulse=tuple(metrics))


def routine_days(view_days: Sequence[date], today: date, warming_up: bool = False) -> int:
    recent = {day for day in view_days if today - timedelta(days=ROUTINE_WINDOW_DAYS) < day <= today}
    needed = WARMUP_ROUTINE_DAYS if warming_up else DAILY_ROUTINE_DAYS
    daily = sum(1 for day in recent if day > today - timedelta(days=14)) >= needed
    weekly = len({day.isocalendar()[:2] for day in recent}) >= WEEKLY_ROUTINE_WEEKS
    return len(recent) if daily or weekly else 0


def is_warming_up(today: date) -> bool:
    """Whether view days have been recorded for too short a time for the daily rule."""
    return (today - VIEW_DAYS_RECORDED_SINCE).days < WARMUP_HISTORY_DAYS


def _routine_insights(context: Context) -> list[ViewedItem]:
    views = FileSystemViewLog.objects.filter(
        team=context.team,
        user=context.user,
        type="insight",
        viewed_at__gte=timezone.now() - timedelta(days=ROUTINE_WINDOW_DAYS),
    ).values_list("ref", "view_days", "viewed_at")
    warming_up = is_warming_up(context.today)
    ranked = sorted(
        (
            (routine_days(days or [], context.today, warming_up), viewed_at, ref, frozenset(days or []))
            for ref, days, viewed_at in views
        ),
        key=lambda row: row[:3],
        reverse=True,
    )
    return [ViewedItem(kind="insight", ref=ref, days=view_days) for days, _at, ref, view_days in ranked if days][
        :ROUTINE_CANDIDATES
    ]


def frecency(view_days: Collection[date], today: date) -> float:
    ages = [(today - day).days for day in view_days]
    return sum(0.5 ** (age / FRECENCY_HALF_LIFE_DAYS) for age in ages if 0 <= age <= FRECENCY_LOOKBACK_DAYS)


def _frecent_metrics(
    context: Context, ranking: str, excluded: Collection[str], budget: int
) -> list[contracts.HighlightMetric]:
    metrics: list[contracts.HighlightMetric] = []
    for item in _frecent_views(context, ranking)[:FRECENCY_CANDIDATES]:
        if len(metrics) >= budget:
            break
        shown = frozenset([*excluded, *(metric.key for metric in metrics)])
        metric = context.guard(f"frecent {item.kind} {item.ref}", partial(_frecent_metric, context, item, shown), None)
        if metric is not None:
            metrics.append(metric)
    return metrics


def _frecent_views(context: Context, ranking: str) -> list[ViewedItem]:
    views = FileSystemViewLog.objects.filter(
        team=context.team,
        user=context.user,
        type__in=("insight", "dashboard") if context.allows("dashboard:read") else ("insight",),
        viewed_at__gte=timezone.now() - timedelta(days=FRECENCY_LOOKBACK_DAYS),
    ).values_list("type", "ref", "view_days", "viewed_at")
    timezone_info = context.team.timezone_info
    items = [
        ViewedItem(kind=kind, ref=ref, days=frozenset({*(days or []), viewed_at.astimezone(timezone_info).date()}))
        for kind, ref, days, viewed_at in views
    ]
    scored = [(frecency(item.days, context.today), max(item.days), item) for item in items]
    if ranking == RECENCY_RANKING:
        scored.sort(key=lambda row: (row[1], row[0]), reverse=True)
    else:
        scored.sort(key=lambda row: row[:2], reverse=True)
    return [item for score, _last, item in scored if score > 0]


def _frecent_metric(context: Context, item: ViewedItem, shown: frozenset[str]) -> contracts.HighlightMetric | None:
    if item.kind == "insight":
        return None if f"insight:{item.ref}" in shown else insight_metric(context, item.ref, viewed=item)
    if not item.ref.isdigit():
        return None
    dashboard = dashboard_insights(
        team=context.team, user=context.user, dashboard_id=int(item.ref), limit=DASHBOARD_TILES_TRIED
    )
    if dashboard is None:
        return None
    for tile in dashboard.tiles:
        if f"insight:{tile.insight_short_id}" in shown:
            continue
        metric = context.guard(
            f"dashboard {item.ref} tile {tile.insight_short_id}",
            partial(_tile_metric, context, dashboard, tile, viewed=item),
            None,
        )
        if metric is not None:
            return metric
    return None


def dashboard_tile_metric(
    context: Context, dashboard_id: int, short_id: str, *, blocking: bool = False
) -> contracts.HighlightMetric | None:
    dashboard = dashboard_insight_tile(
        team=context.team, user=context.user, dashboard_id=dashboard_id, short_id=short_id
    )
    if dashboard is None:
        return None
    return _tile_metric(context, dashboard, dashboard.tiles[0], blocking=blocking)


def _tile_metric(
    context: Context,
    dashboard: DashboardInsights,
    tile: DashboardInsightTile,
    *,
    viewed: ViewedItem | None = None,
    blocking: bool = False,
) -> contracts.HighlightMetric | None:
    return insight_metric(
        context,
        tile.insight_short_id,
        dashboard=InsightDashboardContext(
            filters=dashboard.filters, tile_filters=tile.filters_overrides, variables=dashboard.variables
        ),
        viewed=viewed,
        url=f"/dashboard/{dashboard.dashboard_id}",
        dashboard_name=dashboard.name,
        dashboard_id=dashboard.dashboard_id,
        blocking=blocking,
    )


def insight_metric(
    context: Context,
    short_id: str,
    *,
    viewed: ViewedItem | None = None,
    dashboard: InsightDashboardContext | None = None,
    url: str | None = None,
    dashboard_name: str | None = None,
    dashboard_id: int | None = None,
    blocking: bool = False,
) -> contracts.HighlightMetric | None:
    insight = get_insight_series(
        team=context.team, user=context.user, short_id=short_id, dashboard=dashboard, blocking=blocking
    )
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
    title = short(insight.name or pretty(name), 40)
    if len(series) > 1 and insight.name:
        measured = short(pretty(name), 18)
        title = f"{short(insight.name, 37 - len(measured))} ({measured})"
    return contracts.HighlightMetric(
        key=f"insight:{short_id}",
        name=title,
        value=values[-1],
        unit=HighlightUnit.NUMBER,
        change_pct=round((values[-1] - values[-2]) / abs(values[-2]) * 100, 1) if values[-2] else None,
        series=line,
        interval=HighlightInterval(period),
        url=url or f"/insights/{short_id}",
        value_format=value_format,
        reason=HighlightMetricReason.ROUTINE if dashboard is None else HighlightMetricReason.DASHBOARD,
        dashboard_name=dashboard_name,
        dashboard_id=dashboard_id,
        opened_days=_opened_days(viewed, context.today) if viewed else None,
        last_opened=max(viewed.days) if viewed and viewed.days else None,
        movers=_movers(series, insight.averaged_series, period, context.today),
        previous_value=values[-2],
    )


def _movers(
    series: dict[str, list[tuple[date, float]]], averaged: Sequence[str], period: str, today: date
) -> list[contracts.HighlightMover]:
    if len(series) < 2:
        return []
    moves: list[tuple[float, contracts.HighlightMover]] = []
    for name, points in series.items():
        _, values = detect(points, period, today, period == "day" and name in averaged)
        if len(values) < 2:
            continue
        now, before = values[-1], values[-2]
        mover = contracts.HighlightMover(
            label=short(pretty(name), 32),
            value=now,
            change_pct=round((now - before) / abs(before) * 100, 1) if before else None,
        )
        moves.append((abs(now - before), mover))
    moves.sort(key=lambda move: move[0], reverse=True)
    return [mover for _, mover in moves[:MOVERS_SHOWN]] if len(moves) > 1 else []


def _opened_days(viewed: ViewedItem, today: date) -> int:
    return sum(1 for day in viewed.days if 0 <= (today - day).days < OPENED_DAYS_WINDOW)


SOURCE = Source(name="routine", find=find, scopes=("insight:read",), pulse_order=1)
