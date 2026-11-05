from collections.abc import Collection, Iterable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from functools import partial
from time import monotonic, sleep

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import FileSystemViewLog
from posthog.models.file_system.file_system_view_log import VIEW_DAYS_KEPT

from products.alerts.backend.facade.api import insight_short_ids_watched_by
from products.dashboards.backend.facade.api import (
    DashboardInsights,
    DashboardInsightTile,
    dashboard_insight_tile,
    dashboard_insights,
)
from products.product_analytics.backend.facade.api import (
    get_insight_series,
    insight_query_complete,
    insight_series_supported,
    insight_short_ids_built_by,
    viewable_insight_definitions,
)
from products.product_analytics.backend.facade.contracts import InsightDashboardContext, InsightSeriesNotReady
from products.subscriptions.backend.facade.api import insight_short_ids_subscribed_by

from ...facade import contracts
from ...facade.enums import HighlightInterval, HighlightMetricReason, HighlightUnit, PulseSlotStatus
from ..highlight_rules import short
from ..highlight_series import pretty, usable_series
from ..highlight_trends import complete, detect
from ..highlight_types import Context, Found, Source

FRECENCY_HALF_LIFE_DAYS = 14
FRECENCY_LOOKBACK_DAYS = VIEW_DAYS_KEPT
PULSE_CANDIDATES = 6
BLOCKING_SECONDS = 150
DASHBOARD_TILES_TRIED = 6
OPENED_DAYS_WINDOW = 14
MOVERS_SHOWN = 4
REPEAT_DAYS = 3
REPEAT_WINDOW_DAYS = 28
RECENT_DAYS = 14
BUILT_DAYS = 28
SIGNAL_MIX = (3, 2, 2)
SIGNAL_CANDIDATES = 12


@frozen
class ViewedItem:
    kind: str
    ref: str
    days: frozenset[date]
    reason: HighlightMetricReason | None = None


@frozen
class PulseCandidate:
    viewed: ViewedItem
    short_id: str
    dashboard: DashboardInsights | None = None
    tile: DashboardInsightTile | None = None


@frozen
class PulseChoice:
    key: str
    candidate: PulseCandidate
    slot: contracts.PulseSlot


def find(context: Context) -> Found:
    pinned = context.pinned
    if context.publish_pulse is not None:
        return Found(pulse=tuple(_progressive_metrics(context, pinned, PULSE_CANDIDATES - len(pinned))))
    return Found(pulse=tuple(_frecent_metrics(context, pinned, PULSE_CANDIDATES - len(pinned))))


def _dashboard_context(candidate: PulseCandidate) -> InsightDashboardContext | None:
    if candidate.dashboard is None:
        return None
    return InsightDashboardContext(
        filters=candidate.dashboard.filters,
        tile_filters=candidate.tile.filters_overrides if candidate.tile else None,
        variables=candidate.dashboard.variables,
    )


def _progressive_metrics(context: Context, excluded: Collection[str], budget: int) -> list[contracts.HighlightMetric]:
    if budget <= 0 or context.publish_pulse is None:
        return []
    deadline = monotonic() + BLOCKING_SECONDS
    candidates: list[PulseCandidate] = []
    for item in _own_candidates(context):
        if item.kind == "insight":
            candidates.append(PulseCandidate(viewed=item, short_id=item.ref))
        elif item.ref.isdigit():
            dashboard = dashboard_insights(
                team=context.team, user=context.user, dashboard_id=int(item.ref), limit=DASHBOARD_TILES_TRIED
            )
            if dashboard is not None:
                candidates.extend(
                    PulseCandidate(viewed=item, short_id=tile.insight_short_id, dashboard=dashboard, tile=tile)
                    for tile in dashboard.tiles
                )
    choices = _eligible_choices(context, excluded, candidates)
    selected: dict[str, PulseChoice] = {}
    tried: set[str] = set()
    slots: dict[str, contracts.PulseSlot] = {}
    pending: dict[str, PulseCandidate] = {}

    def fill() -> None:
        while len(selected) < budget:
            choice = _next_choice(choices, tried, selected.values())
            if choice is None:
                return
            tried.add(choice.key)
            selected[choice.key] = choice
            slots[choice.key] = choice.slot
            pending[choice.key] = choice.candidate

    def drop(key: str) -> None:
        slots[key] = replace(slots[key], status=PulseSlotStatus.EMPTY)
        del selected[key]
        fill()

    fill()
    metrics: dict[str, contracts.HighlightMetric] = {}
    context.publish_pulse(Found(), list(slots.values()))
    query_ids: dict[str, str] = {}
    while pending and monotonic() < deadline:
        for key, candidate in list(pending.items()):
            if monotonic() >= deadline:
                break
            dashboard = candidate.dashboard
            try:
                if key in query_ids and not insight_query_complete(team=context.team, query_id=query_ids[key]):
                    continue
                metric = insight_metric(
                    context,
                    candidate.short_id,
                    viewed=candidate.viewed,
                    reason=candidate.viewed.reason,
                    dashboard=_dashboard_context(candidate),
                    url=slots[key].url,
                    dashboard_name=dashboard.name if dashboard else None,
                    dashboard_id=dashboard.dashboard_id if dashboard else None,
                    raise_on_pending=True,
                )
            except InsightSeriesNotReady as error:
                if error.query_id is None:
                    raise ValueError("Pending insight has no query ID") from error
                query_ids[key] = error.query_id
                continue
            except ValueError as error:
                capture_exception(error, {"product": "today", "provider": "routine"})
                metric = None
            except Exception as error:
                context.failures.append(key)
                capture_exception(error, {"product": "today", "provider": "routine"})
                metric = None
            del pending[key]
            if metric is None:
                drop(key)
            else:
                slots[key] = replace(slots[key], status=PulseSlotStatus.READY)
                metrics[key] = metric
            context.publish_pulse(Found(pulse=tuple(metrics.values())), list(slots.values()))
        if pending:
            sleep(min(1.0, max(0, deadline - monotonic())))
    if pending:
        context.failures.extend(pending)
        for key in pending:
            slots[key] = replace(slots[key], status=PulseSlotStatus.ERROR)
        context.publish_pulse(Found(pulse=tuple(metrics.values())), list(slots.values()))
    return [metrics[key] for key in selected if key in metrics]


def _eligible_choices(
    context: Context, excluded: Collection[str], candidates: Sequence[PulseCandidate]
) -> list[PulseChoice]:
    definitions = viewable_insight_definitions(
        team=context.team, user=context.user, short_ids=[candidate.short_id for candidate in candidates]
    )
    choices: list[PulseChoice] = []
    for candidate in candidates:
        key = f"insight:{candidate.short_id}"
        definition = definitions.get(candidate.short_id)
        if key in excluded or definition is None:
            continue
        if not context.guard(
            f"eligible insight {candidate.short_id}",
            partial(insight_series_supported, query=definition.query, dashboard=_dashboard_context(candidate)),
            False,
        ):
            continue
        source = definition.query.get("source", definition.query)
        dashboard = candidate.dashboard
        interval = (dashboard.filters.get("interval") if dashboard else None) or source.get("interval", "day")
        choices.append(
            PulseChoice(
                key=key,
                candidate=candidate,
                slot=contracts.PulseSlot(
                    key=key,
                    name=definition.name or "Untitled insight",
                    reason=candidate.viewed.reason or HighlightMetricReason.ROUTINE,
                    url=f"/dashboard/{dashboard.dashboard_id}" if dashboard else f"/insights/{candidate.short_id}",
                    interval=HighlightInterval(interval)
                    if source.get("kind") == "TrendsQuery" and interval in HighlightInterval.values
                    else None,
                ),
            )
        )
    return choices


def _next_choice(
    choices: Sequence[PulseChoice], tried: Collection[str], selected: Iterable[PulseChoice]
) -> PulseChoice | None:
    shown = {choice.candidate.dashboard.dashboard_id for choice in selected if choice.candidate.dashboard is not None}
    return next(
        (
            choice
            for choice in choices
            if choice.key not in tried
            and (choice.candidate.dashboard is None or choice.candidate.dashboard.dashboard_id not in shown)
        ),
        None,
    )


def frecency(view_days: Collection[date], today: date) -> float:
    ages = [(today - day).days for day in view_days]
    return sum(0.5 ** (age / FRECENCY_HALF_LIFE_DAYS) for age in ages if 0 <= age <= FRECENCY_LOOKBACK_DAYS)


def _frecent_metrics(context: Context, excluded: Collection[str], budget: int) -> list[contracts.HighlightMetric]:
    if budget <= 0:
        return []
    deadline = monotonic() + BLOCKING_SECONDS
    candidates: list[tuple[ViewedItem, contracts.HighlightMetric | None]] = []
    available: set[str] = set()
    for item in _own_candidates(context):
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


def _own_candidates(context: Context) -> list[ViewedItem]:
    none: list[str] = []
    used = [item for item in _frecent_views(context) if _repeated(item.days, context.today)]
    alerted = context.guard(
        "alerted insights",
        partial(
            insight_short_ids_watched_by, team_id=context.team.id, user_id=context.user.id, limit=SIGNAL_CANDIDATES
        ),
        none,
    )
    subscribed = context.guard(
        "subscribed insights",
        partial(
            insight_short_ids_subscribed_by,
            team_id=context.team.id,
            user_id=context.user.id,
            email=context.user.email,
            now=timezone.now(),
            limit=SIGNAL_CANDIDATES,
        ),
        none,
    )
    built = context.guard(
        "built insights",
        partial(
            insight_short_ids_built_by,
            team=context.team,
            user_id=context.user.id,
            since=timezone.now() - timedelta(days=BUILT_DAYS),
            limit=SIGNAL_CANDIDATES,
        ),
        none,
    )
    watched = [*alerted, *subscribed]
    groups = [
        used,
        [
            ViewedItem(kind="insight", ref=ref, days=frozenset(), reason=HighlightMetricReason.WATCHED)
            for ref in dict.fromkeys(watched)
        ],
        [ViewedItem(kind="insight", ref=ref, days=frozenset(), reason=HighlightMetricReason.BUILT) for ref in built],
    ]
    return _mixed(groups, SIGNAL_MIX)[:SIGNAL_CANDIDATES]


def _repeated(view_days: Collection[date], today: date) -> bool:
    ages = [(today - day).days for day in view_days]
    return sum(0 <= age < REPEAT_WINDOW_DAYS for age in ages) >= REPEAT_DAYS and any(
        0 <= age < RECENT_DAYS for age in ages
    )


def _mixed(groups: Sequence[Sequence[ViewedItem]], quotas: Sequence[int]) -> list[ViewedItem]:
    seen: set[tuple[str, str]] = set()
    unique: list[list[ViewedItem]] = []
    for group in groups:
        fresh = [item for item in group if (item.kind, item.ref) not in seen]
        seen.update((item.kind, item.ref) for item in fresh)
        unique.append(fresh)
    return [
        *(item for group, quota in zip(unique, quotas) for item in group[:quota]),
        *(item for group, quota in zip(unique, quotas) for item in group[quota:]),
    ]


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


def _frecent_metric(
    context: Context, item: ViewedItem, shown: frozenset[str], deadline: float, *, wait: bool = True
) -> contracts.HighlightMetric | None:
    if item.kind == "insight":
        if f"insight:{item.ref}" in shown:
            return None
        return insight_metric(
            context,
            item.ref,
            viewed=item,
            reason=item.reason,
            blocking=wait and monotonic() < deadline,
            wait_until=deadline,
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
    context: Context,
    dashboard_id: int,
    short_id: str,
    *,
    blocking: bool = False,
    wait_until: float | None = None,
) -> contracts.HighlightMetric | None:
    dashboard = dashboard_insight_tile(
        team=context.team, user=context.user, dashboard_id=dashboard_id, short_id=short_id
    )
    if dashboard is None:
        return None
    return _tile_metric(context, dashboard, dashboard.tiles[0], blocking=blocking, wait_until=wait_until)


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
    raise_on_pending: bool = False,
) -> contracts.HighlightMetric | None:
    insight = get_insight_series(
        team=context.team,
        user=context.user,
        short_id=short_id,
        dashboard=dashboard,
        blocking=blocking,
        wait_until=wait_until,
        raise_on_pending=raise_on_pending,
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
