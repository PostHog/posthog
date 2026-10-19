import datetime

import pytest

from parameterized import parameterized

from products.signals.dags.inbox_ranking.activity_summary import dag
from products.signals.dags.inbox_ranking.activity_summary.render import (
    AI_HEADER,
    MAX_CHAIN_INTENTS,
    MCP_HEADER,
    REPEATED_INTENT_DAILY_LIMIT,
    UNITS_PER_SOURCE,
    AiPrompt,
    McpCall,
    McpSession,
    PairActivity,
    ProjectionPrices,
    Unit,
    build_input,
    calibration_ratio,
    cap_chain,
    clean_text,
    collapse_repeats,
    job_intents,
    mcp_chain,
    projection_rows,
    sample_units,
    sampling_seed,
)

AS_OF = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)


def _at(days_ago: float, minutes: int = 0) -> datetime.datetime:
    return AS_OF - datetime.timedelta(days=days_ago) + datetime.timedelta(minutes=minutes)


def _session(*intents: str, tool: str = "insight-create", days_ago: float = 1) -> McpSession:
    return McpSession(
        calls=tuple(
            McpCall(at=_at(days_ago, minutes=index), tool=tool, intent=intent) for index, intent in enumerate(intents)
        )
    )


@parameterized.expand(
    [
        ("consecutive repeats collapse", ["a", "a", "b", "b", "a"], ["a", "b", "a"]),
        (
            "short chain is kept whole",
            [str(i) for i in range(MAX_CHAIN_INTENTS)],
            [str(i) for i in range(MAX_CHAIN_INTENTS)],
        ),
        (
            "long chain keeps the head and the last intent",
            [str(i) for i in range(40)],
            [*(str(i) for i in range(MAX_CHAIN_INTENTS - 1)), "39"],
        ),
    ]
)
def test_collapse_and_cap(_name: str, intents: list[str], expected: list[str]) -> None:
    assert cap_chain(collapse_repeats(intents)) == expected


def test_chain_drops_plumbing_calls_and_thin_sessions() -> None:
    session = McpSession(
        calls=(
            McpCall(at=_at(1, 0), tool="read-data-schema", intent="Checking the event schema"),
            McpCall(at=_at(1, 1), tool="insight-create", intent="Build a signup funnel"),
            McpCall(at=_at(1, 2), tool="switch-project", intent="Switch to the main project"),
            McpCall(at=_at(1, 3), tool="dashboard-create", intent="Add the funnel to a dashboard"),
        )
    )
    unit = mcp_chain(session, frozenset())
    assert unit is not None
    assert unit.text == "Build a signup funnel --> Add the funnel to a dashboard"

    only_plumbing = _session("Find the project", "Read the schema", tool="project-get")
    assert mcp_chain(only_plumbing, frozenset()) is None


def test_repeated_intent_on_one_day_is_treated_as_a_job() -> None:
    polling = [
        _session("Poll the dashboard", "Read the insight", days_ago=1) for _ in range(REPEATED_INTENT_DAILY_LIMIT + 1)
    ]
    occasional = [
        _session("Poll the dashboard", "Read the insight", days_ago=3) for _ in range(REPEATED_INTENT_DAILY_LIMIT)
    ]
    jobs = job_intents([*polling, *occasional])

    assert mcp_chain(polling[0], jobs) is None
    unit = mcp_chain(occasional[0], jobs)
    assert unit is not None and unit.text == "Poll the dashboard --> Read the insight"


@parameterized.expand(
    [
        ("email", "Ask jane.doe+test@example.com about it", "Ask <email> about it"),
        (
            "url query string",
            "Open https://example.com/insights/abc?token=xyz&a=1 now",
            "Open https://example.com/insights/abc now",
        ),
        ("token-like string", "Use key phx_9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c", "Use key <token>"),
        ("multiline text folds onto one line", "First line\n\n  second\tline ", "First line second line"),
        (
            "ordinary text is untouched",
            "Why did weekly signups drop in October?",
            "Why did weekly signups drop in October?",
        ),
    ]
)
def test_clean_text(_name: str, text: str, expected: str) -> None:
    assert clean_text(text) == expected


def test_sampling_is_deterministic_and_favors_recent_units() -> None:
    units = [Unit(at=_at(days_ago), text=f"unit {days_ago}") for days_ago in range(28)]
    seed = sampling_seed("2026-10-18", 2, 7)

    first = sample_units(units, limit=UNITS_PER_SOURCE, as_of=AS_OF, seed=seed)
    assert first == sample_units(list(reversed(units)), limit=UNITS_PER_SOURCE, as_of=AS_OF, seed=seed)
    assert len(first) == UNITS_PER_SOURCE
    assert first == sorted(first, key=lambda unit: unit.at)

    picked_ages = [
        (AS_OF - unit.at).days
        for partition in range(50)
        for unit in sample_units(units, limit=UNITS_PER_SOURCE, as_of=AS_OF, seed=sampling_seed(str(partition), 2, 7))
    ]
    assert sum(1 for age in picked_ages if age < 7) > sum(1 for age in picked_ages if age >= 21)


def test_build_input_renders_deduped_chains_then_prompts() -> None:
    sessions = [
        _session("Build a signup funnel", "Add it to a dashboard", days_ago=3),
        _session("Build a signup funnel", "Add it to a dashboard", days_ago=1),
        _session("Compare retention by plan", "Save the insight", days_ago=2),
    ]
    prompts = [
        AiPrompt(at=_at(4), prompt="Why did signups drop?"),
        AiPrompt(at=_at(2), prompt="Why did signups drop?"),
        AiPrompt(at=_at(1), prompt="  "),
    ]

    rendered = build_input(sessions, prompts, jobs=frozenset(), as_of=AS_OF, seed=1)

    assert rendered is not None
    assert rendered.text == "\n".join(
        [
            MCP_HEADER,
            "Compare retention by plan --> Save the insight",
            "Build a signup funnel --> Add it to a dashboard",
            AI_HEADER,
            "Why did signups drop?",
        ]
    )
    assert (rendered.n_mcp_sessions, rendered.n_ai_conversations) == (2, 1)
    assert rendered.input_chars == len(rendered.text)
    assert build_input([], [AiPrompt(at=_at(1), prompt="")], jobs=frozenset(), as_of=AS_OF, seed=1) is None


def test_projection_counts_eligible_pairs_and_caps_updates_by_cadence() -> None:
    activities = [
        PairActivity(mcp_sessions=2, mcp_chain_chars=200.0, ai_conversations=0, ai_prompt_chars=0.0),
        PairActivity(mcp_sessions=20, mcp_chain_chars=4000.0, ai_conversations=20, ai_prompt_chars=2000.0),
    ]
    prices = ProjectionPrices(
        prompt_overhead_tokens=0,
        output_tokens_per_update=0,
        input_price_per_million_tokens=None,
        output_price_per_million_tokens=None,
    )

    rows = {(row["min_units"], row["min_days"]): row for row in projection_rows(activities, ratio=1.0, prices=prices)}

    assert rows[(3, 7)]["eligible_pairs"] == 1
    # 40 units would earn 13 updates at 3 units each, but a 7-day cadence allows 4 in the 28-day window.
    assert rows[(3, 7)]["updates_per_month"] == pytest.approx(4 * 30 / 28)
    assert rows[(10, 14)]["updates_per_month"] == pytest.approx(2 * 30 / 28)
    assert all(row["projected_monthly_cost_usd"] is None for row in rows.values())


def test_calibration_ratio_ignores_unmatched_pairs() -> None:
    assert calibration_ratio({(1, "a"): 300, (1, "b"): 999}, {(1, "a"): 200, (2, "c"): 50}) == pytest.approx(1.5)
    assert calibration_ratio({}, {(1, "a"): 200}) == 1.0


def test_asset_rows_match_their_schemas_and_skip_projects_outside_the_organization() -> None:
    window = dag.activity_window("2026-10-18")
    sessions = {
        ("member", "own-project"): [_session("Build a signup funnel", "Add it to a dashboard")],
        ("member", "customer-project"): [_session("Debug a customer's flag", "Read its rollout")],
    }

    rows = dag.input_rows(
        sessions=sessions,
        prompts={},
        users={"member": 7},
        projects={"own-project": 2},
        window=window,
        partition_key="2026-10-18",
    )

    assert [row["team_id"] for row in rows] == [2]
    assert set(rows[0]) == set(dag.INPUTS_SCHEMA.names)
    projection = projection_rows(
        [PairActivity(mcp_sessions=5, mcp_chain_chars=500.0, ai_conversations=0, ai_prompt_chars=0.0)],
        ratio=1.0,
        prices=ProjectionPrices(
            prompt_overhead_tokens=0,
            output_tokens_per_update=0,
            input_price_per_million_tokens=1.0,
            output_price_per_million_tokens=1.0,
        ),
    )
    assert set(projection[0]) | {"window_start", "window_end"} == set(dag.COST_PROJECTION_SCHEMA.names)
