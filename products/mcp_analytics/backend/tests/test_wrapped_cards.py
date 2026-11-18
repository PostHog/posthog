from parameterized import parameterized

from products.mcp_analytics.backend.wrapped.cards import Archetype, WrappedCards, build_wrapped_cards
from products.mcp_analytics.backend.wrapped.queries import DimensionRow, WrappedAggregates

DEFAULT_MONTHS = {"2026-07": 400, "2026-08": 600}


def _row(key: str, calls: int, errors: int = 0, p95: float | None = 100.0, without_duration: int = 0) -> DimensionRow:
    return DimensionRow(
        key=key, calls=calls, errors=errors, p95_duration_ms=p95, calls_without_duration=without_duration
    )


def _rows(counts: dict[str, int]) -> tuple[DimensionRow, ...]:
    return tuple(_row(key, calls) for key, calls in counts.items())


def _aggregates(
    *,
    months: dict[str, int] = DEFAULT_MONTHS,
    tools: tuple[DimensionRow, ...] | None = None,
    harnesses: dict[str, int] | None = None,
    labs: dict[str, int] | None = None,
    families: dict[str, int] | None = None,
    week_hours: dict[str, int] | None = None,
    errors: int = 0,
    p95: float | None = 400.0,
    without_duration: int = 0,
) -> WrappedAggregates:
    total_calls = sum(months.values())
    return WrappedAggregates(
        total=_row("", total_calls, errors=errors, p95=p95, without_duration=without_duration),
        tools=tools if tools is not None else (_row("get_forecast", total_calls),),
        harnesses=_rows(harnesses if harnesses is not None else {"Claude Code": total_calls}),
        labs=_rows(labs if labs is not None else {"Unknown": total_calls}),
        model_families=_rows(families if families is not None else {"Unknown": total_calls}),
        servers=_rows({"weather": total_calls}),
        months=tuple(_row(f"{month}-01", calls) for month, calls in months.items()),
        week_hours=_rows(week_hours if week_hours is not None else {"216": total_calls}),
    )


def _build(aggregates: WrappedAggregates) -> WrappedCards:
    cards = build_wrapped_cards(aggregates, "UTC")
    assert cards is not None
    return cards


@parameterized.expand(
    [
        ("one_busy_month", {"2026-07": 150}, None),
        ("second_month_below_the_bar", {"2026-07": 99, "2026-08": 150}, None),
        ("test_install_month_is_skipped", {"2026-06": 20, "2026-07": 150, "2026-08": 300}, "2026-07"),
    ]
)
def test_eligibility_and_tracked_since(_name: str, months: dict[str, int], tracked_since: str | None) -> None:
    cards = build_wrapped_cards(_aggregates(months=months), "UTC")

    if tracked_since is None:
        assert cards is None
    else:
        assert cards is not None
        assert cards.intro.tracked_since == tracked_since
        assert [month.month for month in cards.tool_calls.months] == ["2026-07", "2026-08"]


@parameterized.expand(
    [
        ("counts_from_the_first_full_month", {"2026-07": 120, "2026-08": 200, "2026-11": 1000}, 5.0),
        ("two_months_have_no_full_month_to_compare", {"2026-07": 120, "2026-08": 200}, None),
        ("too_little_growth_to_mention", {"2026-07": 120, "2026-08": 200, "2026-09": 250}, None),
    ]
)
def test_growth_multiple(_name: str, months: dict[str, int], expected: float | None) -> None:
    assert _build(_aggregates(months=months)).tool_calls.growth_multiple == expected


def test_top_tools_and_struggling_tool_leave_out_the_exec_bucket() -> None:
    tools = (
        _row("exec", 500, errors=400),
        _row("get_forecast", 300, errors=3),
        _row("list_alerts", 150, errors=30),
        _row("create_alert", 50, errors=50),
    )

    cards = _build(_aggregates(tools=tools))

    assert [tool.tool for tool in cards.top_tools.tools] == ["get_forecast", "list_alerts", "create_alert"]
    assert cards.reliability.struggling_tool is None, "only two tools have enough calls to rank"

    tools_with_three = (*tools, _row("get_history", 100, errors=1))
    struggling = _build(_aggregates(tools=tools_with_three)).reliability.struggling_tool
    assert struggling is not None
    assert (struggling.tool, struggling.error_rate) == ("list_alerts", 0.2)


@parameterized.expand(
    [
        ("mostly_known_clients", {"Claude Code": 700, "Cursor": 200, "Other": 100}, ["Claude Code", "Cursor", "Other"]),
        ("too_many_unknown_clients", {"Claude Code": 700, "Other": 300}, None),
    ]
)
def test_apps_card(_name: str, harnesses: dict[str, int], labels: list[str] | None) -> None:
    apps = _build(_aggregates(harnesses=harnesses)).apps

    assert (apps and [share.label for share in apps.shares]) == labels


@parameterized.expand(
    [
        ("too_few_calls_carry_a_model", {"Anthropic": 200, "Unknown": 800}, {"Claude Sonnet": 200}, None),
        (
            "too_many_models_match_no_lab",
            {"Anthropic": 400, "Other": 100, "Unknown": 500},
            {"Claude Sonnet": 400},
            None,
        ),
        (
            "enough_known_models",
            {"Anthropic": 450, "OpenAI": 50, "Unknown": 500},
            {"Claude Sonnet": 300, "Claude Opus": 150, "GPT-6": 50, "Unknown": 500},
            ["Claude Sonnet", "Claude Opus", "GPT-6"],
        ),
    ]
)
def test_labs_and_models_cards(
    _name: str, labs: dict[str, int], families: dict[str, int], family_labels: list[str] | None
) -> None:
    cards = _build(_aggregates(labs=labs, families=families))

    if family_labels is None:
        assert cards.labs is None and cards.models is None
    else:
        assert cards.labs is not None and cards.models is not None
        assert [(share.label, share.share) for share in cards.labs.shares] == [("Anthropic", 0.9), ("OpenAI", 0.1)]
        assert [share.label for share in cards.models.shares] == family_labels


def test_rush_hour_needs_enough_calls_and_finds_the_busiest_slot() -> None:
    small = _build(_aggregates(months={"2026-07": 400, "2026-08": 500}))
    busy = _build(_aggregates(week_hours={"216": 600, "623": 300, "101": 100}))

    assert small.rush_hour is None
    rush_hour = busy.rush_hour
    assert rush_hour is not None
    assert (rush_hour.weekday, rush_hour.hour, rush_hour.timezone) == (2, 16, "UTC")
    assert (rush_hour.heat[(2 - 1) * 24 + 16], rush_hour.heat[(6 - 1) * 24 + 23], rush_hour.heat[0]) == (100, 50, 0)


@parameterized.expand(
    [
        ("busy_weekends_and_days", {"216": 600, "614": 400}, False, False),
        ("quiet_weekends", {"216": 900, "614": 100}, True, False),
        ("night_shift", {"223": 600, "210": 400}, True, True),
    ]
)
def test_rush_hour_wording_flags(
    _name: str, week_hours: dict[str, int], quiet_weekends: bool, night_shift: bool
) -> None:
    rush_hour = _build(_aggregates(week_hours=week_hours)).rush_hour

    assert rush_hour is not None
    assert (rush_hour.quiet_weekends, rush_hour.night_shift) == (quiet_weekends, night_shift)


@parameterized.expand(
    [
        ("missing_durations_hide_the_card", 300, False),
        ("enough_durations", 299, True),
    ]
)
def test_speed_card_visibility(_name: str, without_duration: int, shown: bool) -> None:
    speed = _build(_aggregates(without_duration=without_duration)).speed

    assert (speed is not None) == shown


def test_speed_names_the_quickest_busy_tool_and_the_slowest_tool() -> None:
    tools = (
        _row("get_forecast", 500, p95=300.0),
        _row("list_alerts", 300, p95=40.0),
        _row("get_history", 150, p95=2400.0400000001),
        _row("exec", 900, p95=1.0),
    )

    speed = _build(_aggregates(tools=tools)).speed

    assert speed is not None and speed.quickest_busy_tool is not None and speed.slowest_tool is not None
    assert (speed.quickest_busy_tool.tool, speed.slowest_tool.tool) == ("list_alerts", "get_history")
    assert speed.slowest_tool.p95_duration_ms == 2400.0


@parameterized.expand(
    [
        (
            "one_hit_wonder",
            {"tools": (_row("get_forecast", 700), _row("list_alerts", 300))},
            Archetype.ONE_HIT_WONDER,
            0.7,
        ),
        (
            "swiss_army_knife",
            {"tools": tuple(_row(f"tool_{i}", 125) for i in range(8))},
            Archetype.SWISS_ARMY_KNIFE,
            8,
        ),
        (
            "night_owl",
            {"tools": (_row("a", 500), _row("b", 500)), "week_hours": {"223": 500, "210": 500}},
            Archetype.NIGHT_OWL,
            0.5,
        ),
        (
            "weekend_warrior",
            {"tools": (_row("a", 500), _row("b", 500)), "week_hours": {"614": 400, "210": 600}},
            Archetype.WEEKEND_WARRIOR,
            0.4,
        ),
        ("speed_demon", {"tools": (_row("a", 500), _row("b", 500)), "p95": 200.0}, Archetype.SPEED_DEMON, 200.0),
        (
            "rocket",
            {
                "tools": (_row("a", 1100), _row("b", 1100)),
                "months": {"2026-07": 100, "2026-08": 200, "2026-11": 1900},
            },
            Archetype.ROCKET,
            9.5,
        ),
        ("all_rounder", {"tools": (_row("a", 500), _row("b", 500))}, Archetype.ALL_ROUNDER, None),
    ]
)
def test_archetype(_name: str, overrides: dict, archetype: Archetype, evidence: float | None) -> None:
    card = _build(_aggregates(**overrides)).archetype

    assert (card.archetype, card.evidence) == (archetype, evidence)
