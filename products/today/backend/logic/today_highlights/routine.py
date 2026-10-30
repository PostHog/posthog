from collections.abc import Collection, Iterator, Sequence
from datetime import date, timedelta
from functools import partial
from time import monotonic

from django.db.models import Count, Max
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
from ..highlight_rules import short
from ..highlight_series import pretty, usable_series
from ..highlight_trends import complete, detect
from ..highlight_types import Context, Found, Source

FRECENCY_HALF_LIFE_DAYS = 14
FRECENCY_LOOKBACK_DAYS = VIEW_DAYS_KEPT
FRECENCY_CANDIDATES = 8
PULSE_CANDIDATES = 6
BLOCKING_SECONDS = 20
POPULAR_DAYS = 30
POPULAR_CANDIDATES = 8
DASHBOARD_TILES_TRIED = 6
OPENED_DAYS_WINDOW = 14
MOVERS_SHOWN = 4


@frozen
class ViewedItem:
    kind: str
    ref: str
    days: frozenset[date]
    popular: bool = False


def find(context: Context) -> Found:
    pinned = context.pinned
    return Found(pulse=tuple(_frecent_metrics(context, pinned, PULSE_CANDIDATES - len(pinned))))


def frecency(view_days: Collection[date], today: date) -> float:
    ages = [(today - day).days for day in view_days]
    return sum(0.5 ** (age / FRECENCY_HALF_LIFE_DAYS) for age in ages if 0 <= age <= FRECENCY_LOOKBACK_DAYS)


def _frecent_metrics(context: Context, excluded: Collection[str], budget: int) -> list[contracts.HighlightMetric]:
    if budget <= 0:
        return []
    deadline = monotonic() + BLOCKING_SECONDS
    candidates: list[tuple[ViewedItem, contracts.HighlightMetric | None]] = []
    available: set[str] = set()
    for item in _candidates(context, _frecent_views(context)[:FRECENCY_CANDIDATES]):
        shown = frozenset([*excluded, *available])
        metric = context.guard(
            f"frecent {item.kind} {item.ref}",
            partial(_frecent_metric, context, item, shown, deadline, wait=False),
            None,
        )
        candidates.append((item, metric))
        if metric is not None:
            available.add(metric.key)
        if len(available) >= budget:
            break

    metrics: list[contracts.HighlightMetric] = []
    for item, metric in candidates:
        if len(metrics) >= budget:
            break
        shown = frozenset([*excluded, *(metric.key for metric in metrics)])
        if metric is None or metric.key in shown:
            metric = context.guard(
                f"frecent {item.kind} {item.ref}", partial(_frecent_metric, context, item, shown, deadline), None
            )
        if metric is not None:
            metrics.append(metric)
    return metrics


def _candidates(context: Context, own: list[ViewedItem]) -> Iterator[ViewedItem]:
    yield from own
    known = {item.ref for item in own if item.kind == "insight"}
    popular: list[str] = context.guard(
        "popular insights", partial(context.daily, "popular_insights", partial(_popular_refs, context)), []
    )
    for ref in [ref for ref in popular if ref not in known][:POPULAR_CANDIDATES]:
        yield ViewedItem(kind="insight", ref=ref, days=frozenset(), popular=True)


def _frecent_views(context: Context) -> list[ViewedItem]:
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
    scored.sort(key=lambda row: row[:2], reverse=True)
    return [item for score, _last, item in scored if score > 0]


def _popular_refs(context: Context) -> list[str]:
    rows = (
        FileSystemViewLog.objects.filter(
            team=context.team, type="insight", viewed_at__gte=timezone.now() - timedelta(days=POPULAR_DAYS)
        )
        .values("ref")
        .annotate(viewers=Count("user_id", distinct=True), last_viewed=Max("viewed_at"))
        .order_by("-viewers", "-last_viewed", "ref")[: POPULAR_CANDIDATES + FRECENCY_CANDIDATES]
    )
    return [row["ref"] for row in rows]


def _frecent_metric(
    context: Context, item: ViewedItem, shown: frozenset[str], deadline: float, *, wait: bool = True
) -> contracts.HighlightMetric | None:
    if item.kind == "insight":
        if f"insight:{item.ref}" in shown:
            return None
        if item.popular:
            return insight_metric(
                context,
                item.ref,
                reason=HighlightMetricReason.POPULAR,
                blocking=wait and monotonic() < deadline,
                wait_until=deadline,
            )
        return insight_metric(
            context, item.ref, viewed=item, blocking=wait and monotonic() < deadline, wait_until=deadline
        )
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
            partial(
                _tile_metric,
                context,
                dashboard,
                tile,
                viewed=item,
                blocking=wait and monotonic() < deadline,
                wait_until=deadline,
            ),
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
    wait_until: float | None = None,
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
        wait_until=wait_until,
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
    reason: HighlightMetricReason | None = None,
    blocking: bool = False,
    wait_until: float | None = None,
) -> contracts.HighlightMetric | None:
    insight = get_insight_series(
        team=context.team,
        user=context.user,
        short_id=short_id,
        dashboard=dashboard,
        blocking=blocking,
        wait_until=wait_until,
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
        reason=reason or (HighlightMetricReason.ROUTINE if dashboard is None else HighlightMetricReason.DASHBOARD),
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
