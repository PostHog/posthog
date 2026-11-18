"""Turn a period's aggregates into MCP Wrapped cards.

Pure: no database, no clock. Every rule that decides whether a card is shown, or how it is worded, lives here,
so a card only appears when its numbers mean something for that project. A hidden card is `None`, and the story
skips it. The cards hold only what the story shows, so the stored payload stays small whatever the project's size.
"""

from collections.abc import Iterable, Sequence
from datetime import date

from posthog.dataclasses import frozen

from products.mcp_analytics.backend.facade.enums import Archetype
from products.mcp_analytics.backend.wrapped.model_families import OTHER_FAMILY, UNKNOWN_FAMILY
from products.mcp_analytics.backend.wrapped.queries import DimensionRow, MonthCalls, WrappedAggregates

SCHEMA_VERSION = 2

# A project needs this many months with real traffic. One month leaves the monthly cards nothing to compare,
# and the first month is often a test install.
MIN_MONTH_CALLS = 100
MIN_ACTIVE_MONTHS = 2

# 168 weekday-hour slots need about this many calls before the busiest one stops being chance.
MIN_RUSH_HOUR_CALLS = 1000
# A tool's error rate or p95 over fewer calls is a handful of calls, not a property of the tool.
MIN_TOOL_CALLS = 100
MIN_TOOLS_FOR_WORST = 3
MIN_TOOLS_FOR_SPEED = 2
# Calls with no client signal land in "Other", so a large "Other" says more about missing data than about clients.
MAX_OTHER_HARNESS_SHARE = 0.2
MIN_MODEL_COVERAGE = 0.3
MIN_KNOWN_LAB_SHARE = 0.9
MAX_MISSING_DURATION_SHARE = 0.3
MIN_GROWTH_MULTIPLE = 1.5
QUIET_WEEKEND_SHARE = 0.15
NIGHT_SHIFT_SHARE = 0.5

TOP_TOOLS = 5
TOP_HARNESSES = 3
TOP_LABS = 4
TOP_MODEL_FAMILIES = 4
# The heatmap only shades cells, so it stores intensity on this scale instead of raw counts.
HEAT_LEVELS = 100

# Discovery calls on single-exec servers stay under the dispatcher's name, which is not a tool anyone chose.
EXCLUDED_TOOLS = frozenset({"exec", ""})
OTHER_HARNESS = "Other"
UNKNOWN_LAB = "Unknown"
OTHER_LAB = "Other"
OTHER_SHARE_LABEL = "Other"

WEEKEND_DAYS = frozenset({6, 7})
NIGHT_HOURS = frozenset({22, 23, 0, 1, 2, 3, 4, 5})

ONE_HIT_WONDER_SHARE = 0.6
SWISS_ARMY_KNIFE_TOOLS = 6
SWISS_ARMY_KNIFE_TOOL_SHARE = 0.05
NIGHT_OWL_SHARE = 0.4
WEEKEND_WARRIOR_SHARE = 0.35
SPEED_DEMON_P95_MS = 250
ROCKET_GROWTH_MULTIPLE = 5
# Reliable and quick together, for a server with no stronger usage pattern than doing its job well.
SUPERHERO_SUCCESS_RATE = 0.995
SUPERHERO_P95_MS = 1000


@frozen
class Share:
    name: str
    share: float


@frozen
class MonthTotal:
    # "2026-07"
    month: str
    calls: int


@frozen
class ToolCalls:
    tool: str
    calls: int


@frozen
class IntroCard:
    tracked_since: str
    server_count: int


@frozen
class ToolCallsCard:
    total_calls: int
    months: tuple[MonthTotal, ...]
    # The last month over the first full month, set only when it grew enough to say so.
    growth_multiple: float | None


@frozen
class TopToolsCard:
    tools: tuple[ToolCalls, ...]


@frozen
class SharesCard:
    shares: tuple[Share, ...]


@frozen
class RushHourCard:
    # ISO weekday, 1 is Monday. The hour is in `timezone`, which the card names because callers are worldwide.
    weekday: int
    hour: int
    timezone: str
    # Intensity from 0 to HEAT_LEVELS per slot, index (weekday - 1) * 24 + hour.
    heat: tuple[int, ...]
    quiet_weekends: bool
    night_shift: bool


@frozen
class ToolErrorRate:
    tool: str
    error_rate: float
    calls: int


@frozen
class ReliabilityCard:
    success_rate: float
    # The lowest error rate among busy tools, with more calls winning a tie.
    most_reliable_tool: ToolErrorRate | None
    struggling_tool: ToolErrorRate | None


@frozen
class ToolLatency:
    tool: str
    p95_duration_ms: float


@frozen
class SpeedCard:
    p95_duration_ms: float
    quickest_busy_tool: ToolLatency | None
    slowest_tool: ToolLatency | None


@frozen
class ArchetypeCard:
    archetype: Archetype
    # The number that earned the archetype, which the card quotes: a share, a tool count, a p95 or a multiple.
    evidence: float | None


@frozen
class WrappedCards:
    intro: IntroCard
    tool_calls: ToolCallsCard
    top_tools: TopToolsCard
    apps: SharesCard | None
    labs: SharesCard | None
    models: SharesCard | None
    rush_hour: RushHourCard | None
    reliability: ReliabilityCard
    speed: SpeedCard | None
    archetype: ArchetypeCard


def is_eligible(monthly: Iterable[MonthCalls]) -> bool:
    return sum(1 for month in monthly if month.calls >= MIN_MONTH_CALLS) >= MIN_ACTIVE_MONTHS


def build_wrapped_cards(aggregates: WrappedAggregates, timezone: str) -> WrappedCards | None:
    """The cards for an eligible project, or None when the filtered calls fall short of the bar."""
    months = _months_from(aggregates.months)
    if not is_eligible(months):
        return None
    tracked_since = next(month.month for month in months if month.calls >= MIN_MONTH_CALLS)
    shown_months = [month for month in months if month.month >= tracked_since]

    total = aggregates.total
    tool_calls = _tool_calls_card(shown_months, total.calls)
    rush_hour = _rush_hour_card(aggregates.week_hours, total.calls, timezone)
    speed = _speed_card(aggregates)
    return WrappedCards(
        intro=IntroCard(
            tracked_since=_month_label(tracked_since),
            server_count=sum(1 for row in aggregates.servers if row.key and row.calls >= total.calls * 0.01),
        ),
        tool_calls=tool_calls,
        top_tools=TopToolsCard(
            tools=tuple(
                ToolCalls(tool=row.key, calls=row.calls) for row in _ranked(_chosen_tools(aggregates.tools))[:TOP_TOOLS]
            )
        ),
        apps=_apps_card(aggregates.harnesses, total.calls),
        labs=_labs_card(aggregates),
        models=_models_card(aggregates),
        rush_hour=rush_hour,
        reliability=_reliability_card(aggregates),
        speed=speed,
        archetype=_archetype(aggregates, tool_calls=tool_calls, rush_hour=rush_hour, speed=speed),
    )


def _months_from(rows: Sequence[DimensionRow]) -> list[MonthCalls]:
    """Every calendar month from the first to the last with calls, silent months included as zero."""
    calls_by_month = {date.fromisoformat(row.key[:10]): row.calls for row in rows}
    if not calls_by_month:
        return []
    month, last = min(calls_by_month), max(calls_by_month)
    months: list[MonthCalls] = []
    while month <= last:
        months.append(MonthCalls(month=month, calls=calls_by_month.get(month, 0)))
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return months


def _month_label(month: date) -> str:
    return month.strftime("%Y-%m")


def _ratio(value: float) -> float:
    return round(value, 4)


def _tool_calls_card(months: Sequence[MonthCalls], total_calls: int) -> ToolCallsCard:
    growth: float | None = None
    # The first tracked month usually starts mid-month at install, so growth counts from the month after it.
    if len(months) >= 3 and months[1].calls >= MIN_MONTH_CALLS:
        multiple = months[-1].calls / months[1].calls
        if multiple >= MIN_GROWTH_MULTIPLE:
            growth = round(multiple, 1)
    return ToolCallsCard(
        total_calls=total_calls,
        months=tuple(MonthTotal(month=_month_label(month.month), calls=month.calls) for month in months),
        growth_multiple=growth,
    )


def _chosen_tools(tools: Sequence[DimensionRow]) -> list[DimensionRow]:
    return [row for row in tools if row.key not in EXCLUDED_TOOLS]


def _ranked(rows: Sequence[DimensionRow]) -> list[DimensionRow]:
    return sorted(rows, key=lambda row: (-row.calls, row.key))


def _top_shares(rows: Sequence[DimensionRow], limit: int, denominator: int) -> tuple[Share, ...]:
    if denominator <= 0:
        return ()
    top = _ranked(rows)[:limit]
    shares = [Share(name=row.key, share=_ratio(row.calls / denominator)) for row in top]
    rest = denominator - sum(row.calls for row in top)
    if rest > 0:
        shares.append(Share(name=OTHER_SHARE_LABEL, share=_ratio(rest / denominator)))
    return tuple(shares)


def _apps_card(harnesses: Sequence[DimensionRow], total_calls: int) -> SharesCard | None:
    other_calls = sum(row.calls for row in harnesses if row.key == OTHER_HARNESS)
    if total_calls <= 0 or other_calls / total_calls > MAX_OTHER_HARNESS_SHARE:
        return None
    named = [row for row in harnesses if row.key != OTHER_HARNESS]
    return SharesCard(shares=_top_shares(named, TOP_HARNESSES, total_calls))


def _model_calls(aggregates: WrappedAggregates) -> int | None:
    """Calls that carry a model, or None when too few do, or too many of them map to no known lab."""
    with_model = sum(row.calls for row in aggregates.labs if row.key != UNKNOWN_LAB)
    total = aggregates.total.calls
    if total <= 0 or with_model / total < MIN_MODEL_COVERAGE:
        return None
    known_lab = sum(row.calls for row in aggregates.labs if row.key not in (UNKNOWN_LAB, OTHER_LAB))
    if known_lab / with_model < MIN_KNOWN_LAB_SHARE:
        return None
    return with_model


def _labs_card(aggregates: WrappedAggregates) -> SharesCard | None:
    with_model = _model_calls(aggregates)
    if with_model is None:
        return None
    known = [row for row in aggregates.labs if row.key not in (UNKNOWN_LAB, OTHER_LAB)]
    return SharesCard(shares=_top_shares(known, TOP_LABS, with_model))


def _models_card(aggregates: WrappedAggregates) -> SharesCard | None:
    with_model = _model_calls(aggregates)
    if with_model is None:
        return None
    known = [row for row in aggregates.model_families if row.key not in (UNKNOWN_FAMILY, OTHER_FAMILY)]
    if not known:
        return None
    return SharesCard(shares=_top_shares(known, TOP_MODEL_FAMILIES, with_model))


def _rush_hour_card(week_hours: Sequence[DimensionRow], total_calls: int, timezone: str) -> RushHourCard | None:
    if total_calls < MIN_RUSH_HOUR_CALLS or not week_hours:
        return None
    counts = [0] * (7 * 24)
    weekend = night = 0
    for row in week_hours:
        weekday, hour = divmod(int(row.key), 100)
        counts[(weekday - 1) * 24 + hour] += row.calls
        weekend += row.calls if weekday in WEEKEND_DAYS else 0
        night += row.calls if hour in NIGHT_HOURS else 0
    peak = max(range(len(counts)), key=lambda index: (counts[index], -index))
    return RushHourCard(
        weekday=peak // 24 + 1,
        hour=peak % 24,
        timezone=timezone,
        heat=tuple(round(count * HEAT_LEVELS / counts[peak]) for count in counts),
        quiet_weekends=weekend / total_calls < QUIET_WEEKEND_SHARE,
        night_shift=night / total_calls > NIGHT_SHIFT_SHARE,
    )


def _reliability_card(aggregates: WrappedAggregates) -> ReliabilityCard:
    total = aggregates.total
    success_rate = 1 - total.errors / total.calls if total.calls else 1.0
    candidates = [row for row in _chosen_tools(aggregates.tools) if row.calls >= MIN_TOOL_CALLS]
    if len(candidates) < MIN_TOOLS_FOR_WORST:
        return ReliabilityCard(success_rate=_ratio(success_rate), most_reliable_tool=None, struggling_tool=None)
    best = min(candidates, key=lambda row: (row.errors / row.calls, -row.calls))
    worst = max(candidates, key=lambda row: (row.errors / row.calls, row.calls))
    # Without a gap between the two rates there is no struggling tool to point at, only the same rate twice.
    struggling = worst if worst.errors / worst.calls > best.errors / best.calls else None
    return ReliabilityCard(
        success_rate=_ratio(success_rate),
        most_reliable_tool=_tool_error_rate(best),
        struggling_tool=_tool_error_rate(struggling) if struggling else None,
    )


def _tool_error_rate(row: DimensionRow) -> ToolErrorRate:
    return ToolErrorRate(tool=row.key, error_rate=_ratio(row.errors / row.calls), calls=row.calls)


def _speed_card(aggregates: WrappedAggregates) -> SpeedCard | None:
    total = aggregates.total
    if total.calls <= 0 or total.p95_duration_ms is None:
        return None
    if total.calls_without_duration / total.calls >= MAX_MISSING_DURATION_SHARE:
        return None
    timed = [
        row
        for row in _chosen_tools(aggregates.tools)
        if row.calls - row.calls_without_duration >= MIN_TOOL_CALLS and row.p95_duration_ms is not None
    ]
    quickest: ToolLatency | None = None
    slowest: ToolLatency | None = None
    if len(timed) >= MIN_TOOLS_FOR_SPEED:
        quick = min(_ranked(timed)[:TOP_TOOLS], key=lambda row: (row.p95_duration_ms or 0.0, -row.calls))
        slow = max(timed, key=lambda row: (row.p95_duration_ms or 0.0, row.calls))
        if quick.key != slow.key:
            quickest = ToolLatency(tool=quick.key, p95_duration_ms=_ms(quick.p95_duration_ms))
            slowest = ToolLatency(tool=slow.key, p95_duration_ms=_ms(slow.p95_duration_ms))
    return SpeedCard(p95_duration_ms=_ms(total.p95_duration_ms), quickest_busy_tool=quickest, slowest_tool=slowest)


def _ms(value: float | None) -> float:
    return round(value or 0.0, 1)


def _archetype(
    aggregates: WrappedAggregates,
    *,
    tool_calls: ToolCallsCard,
    rush_hour: RushHourCard | None,
    speed: SpeedCard | None,
) -> ArchetypeCard:
    total_calls = aggregates.total.calls
    tool_shares = sorted((row.calls / total_calls for row in _chosen_tools(aggregates.tools)), reverse=True)
    week_hours = aggregates.week_hours
    if tool_shares and tool_shares[0] > ONE_HIT_WONDER_SHARE:
        return ArchetypeCard(archetype=Archetype.ONE_HIT_WONDER, evidence=_ratio(tool_shares[0]))
    busy_tools = sum(1 for share in tool_shares if share > SWISS_ARMY_KNIFE_TOOL_SHARE)
    if busy_tools >= SWISS_ARMY_KNIFE_TOOLS:
        return ArchetypeCard(archetype=Archetype.SWISS_ARMY_KNIFE, evidence=busy_tools)
    if rush_hour is not None:
        night = sum(row.calls for row in week_hours if int(row.key) % 100 in NIGHT_HOURS) / total_calls
        if night > NIGHT_OWL_SHARE:
            return ArchetypeCard(archetype=Archetype.NIGHT_OWL, evidence=_ratio(night))
        weekend = sum(row.calls for row in week_hours if int(row.key) // 100 in WEEKEND_DAYS) / total_calls
        if weekend > WEEKEND_WARRIOR_SHARE:
            return ArchetypeCard(archetype=Archetype.WEEKEND_WARRIOR, evidence=_ratio(weekend))
    if speed is not None and speed.p95_duration_ms < SPEED_DEMON_P95_MS:
        return ArchetypeCard(archetype=Archetype.SPEED_DEMON, evidence=speed.p95_duration_ms)
    if tool_calls.growth_multiple is not None and tool_calls.growth_multiple >= ROCKET_GROWTH_MULTIPLE:
        return ArchetypeCard(archetype=Archetype.ROCKET, evidence=tool_calls.growth_multiple)
    success_rate = 1 - aggregates.total.errors / total_calls
    if speed is not None and success_rate >= SUPERHERO_SUCCESS_RATE and speed.p95_duration_ms < SUPERHERO_P95_MS:
        return ArchetypeCard(archetype=Archetype.SUPERHERO, evidence=_ratio(success_rate))
    return ArchetypeCard(archetype=Archetype.ALL_ROUNDER, evidence=None)
