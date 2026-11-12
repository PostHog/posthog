from collections.abc import Collection, Iterable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from functools import partial
from time import monotonic, sleep

from django.db.models import Count, Max
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import FileSystemViewLog
from posthog.models.file_system.file_system_view_log import VIEW_DAYS_KEPT

from products.alerts.backend.facade.api import insight_short_ids_watched_by
from products.customer_analytics.backend.facade.api import get_key_metric_names
from products.dashboards.backend.facade.api import (
    DashboardInsights,
    DashboardInsightTile,
    dashboard_insight_tile,
    dashboard_insights,
)
from products.product_analytics.backend.facade.api import (
    get_insight_series,
    insight_query_complete,
    insight_reads_by_agents,
    insight_series_supported,
    insight_short_ids_built_by,
    viewable_insight_definitions,
)
from products.product_analytics.backend.facade.contracts import (
    AgentInsightRead,
    InsightDashboardContext,
    InsightSeriesNotReady,
)
from products.subscriptions.backend.facade.api import insight_short_ids_subscribed_by

from ...facade import contracts
from ...facade.enums import HighlightInterval, HighlightMetricReason, HighlightUnit, PulseSlotStatus
from ..highlight_rules import short
from ..highlight_series import pretty, usable_series
from ..highlight_trends import complete, detect
from ..highlight_types import Context, Found, Source
from ..pulse_pins import INSIGHT_PREFIX

FRECENCY_HALF_LIFE_DAYS = 14
FRECENCY_LOOKBACK_DAYS = VIEW_DAYS_KEPT
PULSE_CANDIDATES = 6
BLOCKING_SECONDS = 150
DASHBOARD_TILES_TRIED = 6
OPENED_DAYS_WINDOW = 14
MOVERS_SHOWN = 4
REPEAT_DAYS = 3
AGENT_REPEAT_DAYS = 2
REPEAT_WINDOW_DAYS = 28
RECENT_DAYS = 14
BUILT_DAYS = 28
SIGNAL_MIX = (3, 2, 2, 2)
SIGNAL_CANDIDATES = 12
ROW_TILES = 4
POPULAR_DAYS = 30
POPULAR_REFS = 12
POPULAR_MIN_VIEWERS = 2


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
    excluded = context.pinned | context.hidden
    return Found(
        pulse=tuple(
            progressive_metrics(
                context,
                excluded,
                PULSE_CANDIDATES - len(context.pinned),
                own_candidates(context, excluded),
                fill_popular=True,
            )
        )
    )


def _dashboard_context(candidate: PulseCandidate) -> InsightDashboardContext | None:
    if candidate.dashboard is None:
        return None
    return InsightDashboardContext(
        filters=candidate.dashboard.filters,
        tile_filters=candidate.tile.filters_overrides if candidate.tile else None,
        variables=candidate.dashboard.variables,
    )


def progressive_metrics(
    context: Context,
    excluded: Collection[str],
    budget: int,
    items: Sequence[ViewedItem],
    *,
    fill_popular: bool = False,
) -> list[contracts.HighlightMetric]:
    if budget <= 0:
        return []
    deadline = monotonic() + BLOCKING_SECONDS
    candidates: list[PulseCandidate] = []
    for item in items:
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
    choices, popular_limit = _with_popular(
        context, excluded, _eligible_choices(context, excluded, candidates), fill_popular
    )
    selected: dict[str, PulseChoice] = {}
    tried: set[str] = set()
    slots: dict[str, contracts.PulseSlot] = {}
    pending: dict[str, PulseCandidate] = {}

    def fill() -> None:
        while len(selected) < budget:
            popular_shown = sum(_is_popular(choice) for choice in selected.values())
            choice = _next_choice(choices, tried, selected.values(), allow_popular=popular_shown < popular_limit)
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


def _key_metric_places(context: Context) -> int:
    if not context.allows("customer_analytics:read"):
        return 0
    none: dict[str, str] = {}
    names = context.guard("key metric names", partial(get_key_metric_names, team=context.team), none)
    return sum(key not in context.pinned and key not in context.hidden for key in names)


def _popular_refs(context: Context) -> list[str]:
    rows = (
        FileSystemViewLog.objects.filter(
            team=context.team, type="insight", viewed_at__gte=timezone.now() - timedelta(days=POPULAR_DAYS)
        )
        .values("ref")
        .annotate(viewers=Count("user_id", distinct=True), last_viewed=Max("viewed_at"))
        .filter(viewers__gte=POPULAR_MIN_VIEWERS)
        .order_by("-viewers", "-last_viewed", "ref")[:POPULAR_REFS]
    )
    return [row["ref"] for row in rows]


def _is_popular(choice: PulseChoice) -> bool:
    return choice.candidate.viewed.reason == HighlightMetricReason.POPULAR


def _popular_places(context: Context, own: Sequence[PulseChoice]) -> int:
    insights = {choice.key for choice in own if choice.candidate.dashboard is None}
    dashboards = {choice.candidate.dashboard.dashboard_id for choice in own if choice.candidate.dashboard is not None}
    return max(0, ROW_TILES - len(context.pinned) - len(insights) - len(dashboards) - _key_metric_places(context))


def _with_popular(
    context: Context, excluded: Collection[str], own: list[PulseChoice], fill_popular: bool
) -> tuple[list[PulseChoice], int]:
    limit = _popular_places(context, own) if fill_popular else 0
    if limit <= 0:
        return own, 0
    return [*own, *_popular_choices(context, excluded, own)], limit


def _popular_choices(context: Context, excluded: Collection[str], own: Sequence[PulseChoice]) -> list[PulseChoice]:
    none: list[str] = []
    refs = context.guard(
        "popular insights", partial(context.daily, "routine_popular_insights", partial(_popular_refs, context)), none
    )
    known = {choice.key for choice in own}
    candidates = [
        PulseCandidate(
            viewed=ViewedItem(kind="insight", ref=ref, days=frozenset(), reason=HighlightMetricReason.POPULAR),
            short_id=ref,
        )
        for ref in refs
        if f"{INSIGHT_PREFIX}{ref}" not in known
    ]
    return _eligible_choices(context, excluded, candidates)


def _next_choice(
    choices: Sequence[PulseChoice],
    tried: Collection[str],
    selected: Iterable[PulseChoice],
    *,
    allow_popular: bool = True,
) -> PulseChoice | None:
    shown = {choice.candidate.dashboard.dashboard_id for choice in selected if choice.candidate.dashboard is not None}
    return next(
        (
            choice
            for choice in choices
            if choice.key not in tried
            and (allow_popular or not _is_popular(choice))
            and (choice.candidate.dashboard is None or choice.candidate.dashboard.dashboard_id not in shown)
        ),
        None,
    )


def frecency(view_days: Collection[date], today: date) -> float:
    ages = [(today - day).days for day in view_days]
    return sum(0.5 ** (age / FRECENCY_HALF_LIFE_DAYS) for age in ages if 0 <= age <= FRECENCY_LOOKBACK_DAYS)


def own_candidates(context: Context, excluded: Collection[str]) -> list[ViewedItem]:
    none: list[str] = []
    skipped = {key.removeprefix(INSIGHT_PREFIX) for key in excluded if key.startswith(INSIGHT_PREFIX)}
    limit = SIGNAL_CANDIDATES + len(skipped)
    used = [
        item
        for item in _frecent_views(context)
        if _repeated(item.days, context.today) and not (item.kind == "insight" and item.ref in skipped)
    ]
    alerted = context.guard(
        "alerted insights",
        partial(insight_short_ids_watched_by, team_id=context.team.id, user_id=context.user.id, limit=limit),
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
            limit=limit,
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
            limit=limit,
        ),
        none,
    )
    no_reads: list[AgentInsightRead] = []
    agent_reads = context.guard(
        "agent insight reads",
        partial(
            insight_reads_by_agents,
            team_id=context.team.id,
            user_id=context.user.id,
            since=context.today - timedelta(days=REPEAT_WINDOW_DAYS - 1),
            min_days=AGENT_REPEAT_DAYS,
            limit=limit,
        ),
        no_reads,
    )
    asked = [
        read.short_id
        for read in agent_reads
        if read.short_id not in skipped and _repeated(read.read_days, context.today, AGENT_REPEAT_DAYS)
    ]
    watched = [ref for ref in (*alerted, *subscribed) if ref not in skipped]
    built = [ref for ref in built if ref not in skipped]
    groups = [
        used,
        [ViewedItem(kind="insight", ref=ref, days=frozenset(), reason=HighlightMetricReason.AGENT) for ref in asked],
        [
            ViewedItem(kind="insight", ref=ref, days=frozenset(), reason=HighlightMetricReason.WATCHED)
            for ref in dict.fromkeys(watched)
        ],
        [ViewedItem(kind="insight", ref=ref, days=frozenset(), reason=HighlightMetricReason.BUILT) for ref in built],
    ]
    return _mixed(groups, SIGNAL_MIX)[:SIGNAL_CANDIDATES]


def _repeated(view_days: Collection[date], today: date, times: int = REPEAT_DAYS) -> bool:
    ages = [(today - day).days for day in view_days]
    return sum(0 <= age < REPEAT_WINDOW_DAYS for age in ages) >= times and any(0 <= age < RECENT_DAYS for age in ages)


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
