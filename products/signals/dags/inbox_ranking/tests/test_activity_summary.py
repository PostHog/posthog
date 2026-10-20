import json
import datetime
from collections import Counter

import pytest

from parameterized import parameterized

from products.signals.dags.inbox_ranking.activity_summary import dag
from products.signals.dags.inbox_ranking.activity_summary.render import (
    ACTIVITY_HEADER,
    ACTIVITY_LINE_CHARS,
    ACTIVITY_LINES,
    MAX_UNITS_PER_DAY,
    MCP_HEADER,
    MCP_LINE_CHARS,
    MCP_LINES,
    REPEATED_INTENT_DAILY_LIMIT,
    SECTIONS_MAX_CHARS,
    TASK_LINE_CHARS,
    TASK_LINES,
    TASKS_HEADER,
    ActivityItem,
    Drop,
    McpCall,
    McpSession,
    PairActivity,
    ProjectionPrices,
    TaskItem,
    Unit,
    activity_units,
    build_input,
    burst_cap,
    calibration_ratio,
    clean_text,
    job_intents,
    mcp_unit,
    projection_rows,
    sample_units,
    sampling_seed,
    task_units,
)

AS_OF = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)


def _at(days_ago: float, minutes: int = 0) -> datetime.datetime:
    return AS_OF - datetime.timedelta(days=days_ago) + datetime.timedelta(minutes=minutes)


def _calls(*steps: tuple[str, str], days_ago: float = 1) -> McpSession:
    return McpSession(
        calls=tuple(
            McpCall(at=_at(days_ago, minutes=index), tool=tool, intent=intent)
            for index, (tool, intent) in enumerate(steps)
        )
    )


def _session(*intents: str, tool: str = "insight-create", days_ago: float = 1) -> McpSession:
    return _calls(*((tool, intent) for intent in intents), days_ago=days_ago)


def _task(title: str, summary: str | None = None, tags: tuple[str, ...] = (), days_ago: float = 1) -> TaskItem:
    return TaskItem(at=_at(days_ago), title=title, summary=summary, tags=tags)


def _change(
    scope: str, activity: str, name: str | None, client: str | None = None, days_ago: float = 1
) -> ActivityItem:
    return ActivityItem(at=_at(days_ago), scope=scope, activity=activity, name=name, client=client)


@parameterized.expand(
    [
        (
            "plumbing and upkeep calls drop out, the line is first step to last step",
            _calls(
                ("read-data-schema", "Check the event schema"),
                ("insight-create", "Build a signup funnel"),
                ("skill-update", "Save handover notes"),
                ("stamphog-review-runs-create", "Request an approval review"),
                ("dashboard-create", "Add the funnel to a dashboard"),
            ),
            "- 2026-10-18 (5 calls) Build a signup funnel → Add the funnel to a dashboard",
            {Drop.PLUMBING_TOOL: 1, Drop.UPKEEP_TOOL: 2},
        ),
        (
            "repeated steps collapse to one",
            _session("Build a funnel", "Build a funnel"),
            "- 2026-10-18 (2 calls) Build a funnel",
            {},
        ),
        (
            "a session with one work call left is thin",
            _calls(("project-get", "Find the project"), ("insight-create", "Build a funnel")),
            None,
            {Drop.PLUMBING_TOOL: 1, Drop.THIN_SESSION: 1},
        ),
    ]
)
def test_mcp_unit(_name: str, session: McpSession, expected: str | None, expected_drops: dict[str, int]) -> None:
    drops: Counter[str] = Counter()
    unit = mcp_unit(session, frozenset(), drops)
    assert (unit.text if unit else None) == expected
    assert dict(drops) == expected_drops


def test_repeated_intent_on_one_day_is_treated_as_a_job() -> None:
    polling = [
        _session("Poll the dashboard", "Read the insight", days_ago=1) for _ in range(REPEATED_INTENT_DAILY_LIMIT + 1)
    ]
    occasional = [
        _session("Poll the dashboard", "Read the insight", days_ago=3) for _ in range(REPEATED_INTENT_DAILY_LIMIT)
    ]
    jobs = job_intents([*polling, *occasional])
    drops: Counter[str] = Counter()

    assert mcp_unit(polling[0], jobs, drops) is None
    unit = mcp_unit(occasional[0], jobs, drops)
    assert unit is not None and unit.text.endswith("Poll the dashboard → Read the insight")
    assert drops[Drop.REPEATED_JOB] == 2


@parameterized.expand(
    [
        (
            "a summary gives the goal, without its label, and the tags",
            _task("why", summary="Goal: find why weekly signups dropped. Done: found a broken form.", tags=("growth",)),
            "- 2026-10-18 [growth] find why weekly signups dropped. Done: found a broken form.",
            {},
        ),
        (
            "a helper task is dropped",
            _task("[sandbox_prompt:repo_selection] You are a selection agent"),
            None,
            {Drop.SANDBOX_PROMPT_TASK: 1},
        ),
        ("a short title with no summary says nothing", _task("root cause"), None, {Drop.BARE_TITLE: 1}),
        (
            "a long title with no summary is kept",
            _task("compare the retention of the two pricing plans over the last quarter"),
            "- 2026-10-18 compare the retention of the two pricing plans over the last quarter",
            {},
        ),
    ]
)
def test_task_units(_name: str, task: TaskItem, expected: str | None, expected_drops: dict[str, int]) -> None:
    drops: Counter[str] = Counter()
    units = task_units([task], drops)
    assert [unit.text for unit in units] == ([expected] if expected else [])
    assert dict(drops) == expected_drops


def test_templated_task_titles_collapse_to_one_line_with_a_count() -> None:
    tasks = [_task(f"Fix failing CI checks in PR #{number}", days_ago=number) for number in (1, 2, 3)]
    units = task_units(tasks, Counter())
    assert [unit.text for unit in units] == ["- 2026-10-18 Fix failing CI checks in PR #N (x3)"]


def test_activity_units_filter_collapse_and_rank_creates_first() -> None:
    drops: Counter[str] = Counter()
    items = [
        _change("TaggedItem", "created", "growth"),
        _change("Insight", "created", "Signup funnel", client="scout:feature-flags"),
        _change("Notebook", "updated", "Daily report 2026-10-18"),
        _change("AlertConfiguration", "created", None),
        _change("Notebook", "updated", "Pricing notes", days_ago=1),
        _change("Notebook", "updated", "Pricing notes", days_ago=2),
        _change("Dashboard", "created", "Growth overview", days_ago=3),
    ]

    units = activity_units(items, drops)

    assert [unit.text for unit in units] == [
        '- 2026-10-16 created Dashboard "Growth overview"',
        '- 2026-10-18 updated Notebook "Pricing notes" (x2)',
    ]
    assert dict(drops) == {
        Drop.NOISY_SCOPE: 1,
        Drop.SCOUT_CLIENT: 1,
        Drop.AUTO_NAMED_OBJECT: 1,
        Drop.UNNAMED_OBJECT: 1,
    }


def test_burst_cap_keeps_the_newest_units_of_a_day() -> None:
    drops: Counter[str] = Counter()
    units = [Unit(at=_at(1, minutes=minute), text=f"unit {minute}") for minute in range(MAX_UNITS_PER_DAY + 2)]

    kept = burst_cap(units, drops)

    assert [unit.text for unit in kept] == [f"unit {minute}" for minute in range(2, MAX_UNITS_PER_DAY + 2)]
    assert drops[Drop.BURST_CAP] == 2


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
        ("long run without a digit is kept", "a-" * 20, ("a-" * 20).strip()),
        ("text is cut to the cap", "x" * 100, "x" * 60),
        (
            "secret across the cap is masked, not cut",
            "a" * 50 + " sk-proj-abcdefghijklmnop1234567890",
            "a" * 50 + " <token>",
        ),
        ("word split by the read bound is dropped", " " * 230 + "ab sk-proj-abcdefghijklmnop1234567890", "ab"),
    ]
)
def test_clean_text(_name: str, text: str, expected: str) -> None:
    assert clean_text(text, 60) == expected


def test_sampling_is_deterministic_and_favors_recent_units() -> None:
    units = [Unit(at=_at(days_ago), text=f"unit {days_ago}") for days_ago in range(28)]
    seed = sampling_seed("2026-10-18", 2, 7)

    first = sample_units(units, limit=MCP_LINES, as_of=AS_OF, seed=seed)
    assert first == sample_units(list(reversed(units)), limit=MCP_LINES, as_of=AS_OF, seed=seed)
    assert len(first) == MCP_LINES
    assert first == sorted(first, key=lambda unit: unit.at)

    picked_ages = [
        (AS_OF - unit.at).days
        for partition in range(50)
        for unit in sample_units(units, limit=MCP_LINES, as_of=AS_OF, seed=sampling_seed(str(partition), 2, 7))
    ]
    assert sum(1 for age in picked_ages if age < 7) > sum(1 for age in picked_ages if age >= 21)


def test_build_input_renders_the_three_sections_in_order() -> None:
    rendered = build_input(
        [_session("Build a signup funnel", "Add it to a dashboard", days_ago=2)],
        [_task("why", summary="Asked: why did signups drop?", tags=("growth",), days_ago=3)],
        [_change("Dashboard", "created", "Growth overview", days_ago=1)],
        jobs=frozenset(),
        as_of=AS_OF,
        seed=1,
    )

    assert rendered is not None
    assert rendered.text == "\n".join(
        [
            TASKS_HEADER,
            "- 2026-10-16 [growth] why did signups drop?",
            "",
            MCP_HEADER,
            "- 2026-10-17 (2 calls) Build a signup funnel → Add it to a dashboard",
            "",
            ACTIVITY_HEADER,
            '- 2026-10-18 created Dashboard "Growth overview"',
        ]
    )
    assert (rendered.n_tasks, rendered.n_mcp_sessions, rendered.n_activity_lines) == (1, 1, 1)
    assert rendered.input_chars == len(rendered.text)
    assert build_input([], [_task("root cause")], [], jobs=frozenset(), as_of=AS_OF, seed=1) is None


def test_build_input_stays_inside_its_bounds_for_a_very_active_person() -> None:
    runaway = "word " * 2000
    sessions = [
        _session(f"{day} {minute} {runaway}", f"{runaway} end", days_ago=day + minute / 100)
        for day in range(28)
        for minute in range(20)
    ]
    tasks = [
        _task(runaway, summary=f"{day} {n} {runaway}", tags=(runaway,) * 20, days_ago=day + 0.01 * n)
        for day in range(28)
        for n in range(20)
    ]
    activity = [_change("Insight", "created", f"{runaway} {n}", days_ago=n % 28) for n in range(500)]

    rendered = build_input(sessions, tasks, activity, jobs=frozenset(), as_of=AS_OF, seed=1)

    assert rendered is not None
    assert (rendered.n_tasks, rendered.n_mcp_sessions, rendered.n_activity_lines) == (
        TASK_LINES,
        MCP_LINES,
        ACTIVITY_LINES,
    )
    tasks_text, mcp_text, activity_text = rendered.text.split("\n\n")
    assert max(len(line) for line in tasks_text.split("\n")[1:]) <= TASK_LINE_CHARS
    assert max(len(line) for line in mcp_text.split("\n")[1:]) <= MCP_LINE_CHARS
    assert max(len(line) for line in activity_text.split("\n")[1:]) <= ACTIVITY_LINE_CHARS
    assert rendered.input_chars <= SECTIONS_MAX_CHARS
    assert rendered.drops[Drop.BURST_CAP] > 0 and rendered.drops[Drop.SAMPLE_CAP] > 0


def test_projection_counts_eligible_pairs_and_caps_updates_by_cadence() -> None:
    activities = [
        PairActivity(mcp_sessions=2, mcp_avg_line_chars=100.0),
        PairActivity(mcp_sessions=40, mcp_avg_line_chars=150.0),
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
    member_own = dag.MemberProject(team_id=2, user_id=7)
    member_customer = dag.MemberProject(team_id=99, user_id=7)
    sessions = {
        dag.PairKey(project="own-project", distinct_id="member"): [
            _session("Build a signup funnel", "Add it to a dashboard")
        ],
        dag.PairKey(project="customer-project", distinct_id="member"): [
            _session("Debug a customer's flag", "Read its rollout")
        ],
    }

    rows = dag.input_rows(
        sessions=sessions,
        tasks={member_customer: [_task("compare the retention of the two pricing plans over the last quarter")]},
        activity={member_own: [_change("Dashboard", "created", "Growth overview")]},
        users={"member": 7},
        projects={"own-project": 2},
        window=window,
        partition_key="2026-10-18",
    )

    assert [row["team_id"] for row in rows] == [2]
    assert set(rows[0]) == set(dag.INPUTS_SCHEMA.names)
    assert json.loads(rows[0]["drops"]) == {}
    projection = projection_rows(
        [PairActivity(mcp_sessions=5, mcp_avg_line_chars=100.0)],
        ratio=1.0,
        prices=ProjectionPrices(
            prompt_overhead_tokens=0,
            output_tokens_per_update=0,
            input_price_per_million_tokens=1.0,
            output_price_per_million_tokens=1.0,
        ),
    )
    assert set(projection[0]) | {"window_start", "window_end"} == set(dag.COST_PROJECTION_SCHEMA.names)
