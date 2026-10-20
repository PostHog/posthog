import io
import json
import datetime
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest
import time_machine

import dagster
import pyarrow as pa
from botocore.exceptions import ClientError
from openai import APIConnectionError
from parameterized import parameterized

from posthog import settings

from products.signals.dags.inbox_ranking.activity_summary import dag
from products.signals.dags.inbox_ranking.activity_summary.embeddings import (
    LandedVector,
    SummaryDocument,
    within_source_ttl,
)
from products.signals.dags.inbox_ranking.activity_summary.prompt import (
    MalformedSummaryError,
    normalize_summary,
    summary_text,
    user_message,
)
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
from products.signals.dags.inbox_ranking.activity_summary.summaries import (
    PIPELINE_DISTINCT_ID,
    SummaryPrices,
    SummaryRequest,
    cost_usd,
    summarize,
    summary_events,
    summary_row,
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


PARTITION = "2026-10-18"
PREFIX = "inbox_ranking"
PREVIOUS = {"summary": "Builds the signup funnel.", "focus_areas": [], "products": ["product_analytics"]}


@parameterized.expand([("with a previous summary", PREVIOUS), ("cold start", None)])
def test_user_message_sends_only_the_rendered_input_and_the_previous_summary(
    _name: str, previous: dict[str, Any] | None
) -> None:
    message = user_message("- 2026-10-17 Build a funnel", previous, datetime.date(2026, 10, 18))
    assert message.startswith("Today is 2026-10-18.")
    assert message.endswith("Recent activity:\n- 2026-10-17 Build a funnel")
    if previous:
        assert json.dumps(PREVIOUS["summary"]) in message
    else:
        assert "Previous summary:\nNone" in message


def _answer(**overrides: Any) -> str:
    return json.dumps(
        {
            "summary": "Builds the signup funnel.",
            "focus_areas": [{"topic": "signup funnel", "strength": "high", "last_seen": "2026-10-17"}],
            "products": ["product_analytics"],
            "recent_shift": "Moved from flags to funnels.",
            **overrides,
        }
    )


@parameterized.expand(
    [
        ("recent_shift is dropped without a previous summary", _answer(), False, {"recent_shift": None}),
        (
            "recent_shift is kept with a previous summary",
            _answer(),
            True,
            {"recent_shift": "Moved from flags to funnels."},
        ),
        ("a 'None' recent_shift becomes null", _answer(recent_shift="None"), True, {"recent_shift": None}),
        ("a 'null' recent_shift becomes null", _answer(recent_shift=" null "), True, {"recent_shift": None}),
        (
            "the summary is cut to the word cap",
            _answer(summary="word " * 80),
            False,
            {"summary": " ".join(["word"] * 60)},
        ),
        (
            "at most six focus areas, an unknown strength is low and a bad date is null",
            _answer(focus_areas=[{"topic": f"t{i}", "strength": "huge", "last_seen": "soon"} for i in range(8)]),
            False,
            {"focus_areas": [{"topic": f"t{i}", "strength": "low", "last_seen": None} for i in range(6)]},
        ),
        (
            "a focus area without a topic is dropped",
            _answer(focus_areas=[{"strength": "high"}]),
            False,
            {"focus_areas": []},
        ),
    ]
)
def test_normalize_summary(_name: str, content: str, had_previous: bool, expected: dict[str, Any]) -> None:
    assert normalize_summary(content, had_previous_summary=had_previous).items() >= expected.items()


@parameterized.expand(
    [
        ("empty", None),
        ("not JSON", "Here is the summary: ..."),
        ("not an object", "[1, 2]"),
        ("no summary", _answer(summary="  ")),
    ]
)
def test_normalize_summary_rejects_a_malformed_answer(_name: str, content: str | None) -> None:
    with pytest.raises(MalformedSummaryError):
        normalize_summary(content, had_previous_summary=False)


def test_summary_text_is_deterministic_and_keeps_the_focus_order() -> None:
    summary = normalize_summary(
        _answer(
            focus_areas=[
                {"topic": "b", "strength": "high", "last_seen": ""},
                {"topic": "a", "strength": "low", "last_seen": ""},
            ]
        ),
        had_previous_summary=False,
    )
    reloaded = json.loads(json.dumps(summary, sort_keys=True))
    assert summary_text(summary) == summary_text(reloaded) == "Builds the signup funnel.\nFocus areas: b; a"
    assert summary_text({**summary, "focus_areas": []}) == "Builds the signup funnel."


@parameterized.expand(
    [
        (
            "both prices",
            1_000_000,
            200_000,
            SummaryPrices(input_price_per_million_tokens=0.1, output_price_per_million_tokens=0.5),
            0.2,
        ),
        (
            "no output price",
            1_000,
            100,
            SummaryPrices(input_price_per_million_tokens=0.1, output_price_per_million_tokens=None),
            None,
        ),
        (
            "no prices",
            1_000,
            100,
            SummaryPrices(input_price_per_million_tokens=None, output_price_per_million_tokens=None),
            None,
        ),
    ]
)
def test_cost_usd(_name: str, tokens_in: int, tokens_out: int, prices: SummaryPrices, expected: float | None) -> None:
    assert cost_usd(tokens_in, tokens_out, prices) == (pytest.approx(expected) if expected is not None else None)


class _FakeLLM:
    def __init__(self, answers: list[str | Exception]):
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
            choices=[SimpleNamespace(message=SimpleNamespace(content=answer))],
        )


_CONNECTION_ERROR = APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]


@parameterized.expand(
    [
        ("a malformed answer is retried once", ["not json", _answer()], "ok", 2, None),
        (
            "two malformed answers fail the row",
            ["not json", "still not json"],
            "failed",
            2,
            "malformed_output: response is not JSON",
        ),
        (
            "a failed request fails the row without a retry",
            [_CONNECTION_ERROR],
            "failed",
            1,
            "api_error: APIConnectionError",
        ),
    ]
)
def test_summarize_retries_a_malformed_answer_once(
    _name: str, answers: list[str | Exception], status: str, attempts: int, error: str | None
) -> None:
    llm = _FakeLLM(answers)
    request = SummaryRequest(team_id=2, user_id=7, rendered_input="- a line", previous_summary=None)
    outcome = summarize(llm, request, model="gpt-6-luna", as_of=datetime.date(2026, 10, 18))  # type: ignore[arg-type]
    row = summary_row(
        request,
        outcome,
        model="gpt-6-luna",
        prices=SummaryPrices(input_price_per_million_tokens=None, output_price_per_million_tokens=None),
    )

    assert len(llm.requests) == attempts
    assert {req["user"] for req in llm.requests} == {PIPELINE_DISTINCT_ID}
    assert (row["status"], row["error"]) == (status, error)
    successful_calls = attempts if not isinstance(answers[0], Exception) else 0
    assert (row["tokens_in"], row["tokens_out"]) == (100 * successful_calls, 20 * successful_calls)
    assert set(row) == set(dag.SUMMARIES_SCHEMA.names)


@parameterized.expand([("text off by default", False), ("text on when asked", True)])
def test_summary_events_carry_free_text_only_when_asked(_name: str, capture_text: bool) -> None:
    request = SummaryRequest(team_id=2, user_id=7, rendered_input="- a line", previous_summary=None)
    outcome = summarize(_FakeLLM([_answer()]), request, model="gpt-6-luna", as_of=datetime.date(2026, 10, 18))  # type: ignore[arg-type]
    row = summary_row(
        request,
        outcome,
        model="gpt-6-luna",
        prices=SummaryPrices(input_price_per_million_tokens=None, output_price_per_million_tokens=None),
    )
    input_row = {"n_tasks": 1, "n_mcp_sessions": 0, "n_activity_lines": 3, "drops": json.dumps({"burst_cap": 4})}

    (event,) = summary_events([row], [input_row], capture_summary_text=capture_text)

    assert {
        "team_id": 2,
        "user_id": 7,
        "status": "ok",
        "n_activity_lines": 3,
        "drops_burst_cap": 4,
    }.items() <= event.properties.items()
    free_text = {"summary_text", "focus_topics"} & event.properties.keys()
    assert free_text == ({"summary_text", "focus_topics"} if capture_text else set())
    if not capture_text:
        assert not any(isinstance(value, str) and "signup" in value for value in event.properties.values())


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}

    def upload_fileobj(self, fileobj: io.IOBase, bucket: str, key: str, ExtraArgs: dict[str, Any]) -> None:
        self.objects[key] = (fileobj.read(), ExtraArgs["Metadata"])

    def _get(self, key: str, operation: str) -> tuple[bytes, dict[str, str]]:
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, operation)
        return self.objects[key]

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self._get(Key, "GetObject")[0])}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Metadata": self._get(Key, "HeadObject")[1]}

    def get_paginator(self, _name: str) -> "_MemoryS3":
        return self

    def paginate(self, *, Bucket: str, Prefix: str):  # noqa: ANN201
        yield {"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]}

    def write(self, table: str, partition: str, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
        key = dag.partition_object_key(PREFIX, table, partition)
        dag.write_parquet(self, "bucket", key, pa.Table.from_pylist(rows, schema=schema))

    def read(self, table: str, partition: str) -> list[dict[str, Any]]:
        table_ = dag.read_parquet_if_exists(self, "bucket", dag.partition_object_key(PREFIX, table, partition))
        return [] if table_ is None else table_.to_pylist()


class _FailingCapture:
    def capture(self, **kwargs: Any) -> None:
        raise RuntimeError("capture is down")

    def shutdown(self) -> None:
        pass


@pytest.fixture
def memory_s3(monkeypatch: pytest.MonkeyPatch) -> _MemoryS3:
    s3 = _MemoryS3()
    monkeypatch.setattr(dag, "skip_unconfigured", lambda context: False)
    monkeypatch.setattr(dag, "s3_client", lambda: s3)
    monkeypatch.setattr(dag, "dataset_bucket", lambda: "bucket")
    monkeypatch.setattr(settings, "INBOX_RANKING_DATASET_S3_PREFIX", PREFIX)
    return s3


def _input_row(team_id: int, user_id: int, text: str) -> dict[str, Any]:
    window = dag.activity_window(PARTITION)
    return {
        "team_id": team_id,
        "user_id": user_id,
        "window_start": window.start,
        "window_end": window.end,
        "n_tasks": 0,
        "n_mcp_sessions": 1,
        "n_activity_lines": 0,
        "rendered_input": text,
        "task_chars": 0,
        "mcp_chars": len(text),
        "activity_chars": 0,
        "input_chars": len(text),
        "input_tokens_estimate": 1,
        "drops": "{}",
        "render_version": 2,
    }


def _summary_row(team_id: int, user_id: int, status: str, summary: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "user_id": user_id,
        "summary_json": json.dumps(summary) if summary else None,
        "summary_text": summary_text(summary) if summary else None,
        "used_previous_summary": False,
        "model": "gpt-6-luna",
        "prompt_version": 1,
        "tokens_in": 1,
        "tokens_out": 1,
        "latency_ms": 1,
        "cost_usd": None,
        "status": status,
        "error": None if summary else "malformed_output: empty response",
    }


def test_summaries_asset_reads_earlier_partitions_only_and_survives_a_failed_capture(
    memory_s3: _MemoryS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_s3.write(
        dag.INPUTS_TABLE,
        PARTITION,
        [_input_row(2, 7, "- input seven"), _input_row(2, 8, "- input eight")],
        dag.INPUTS_SCHEMA,
    )
    older = {"summary": "Older work on flags.", "focus_areas": [], "products": []}
    memory_s3.write(dag.SUMMARIES_TABLE, "2026-10-10", [_summary_row(2, 7, "ok", older)], dag.SUMMARIES_SCHEMA)
    memory_s3.write(
        dag.SUMMARIES_TABLE,
        "2026-10-17",
        [_summary_row(2, 7, "ok", PREVIOUS), _summary_row(2, 8, "failed", None)],
        dag.SUMMARIES_SCHEMA,
    )
    memory_s3.write(dag.SUMMARIES_TABLE, "2026-10-19", [_summary_row(2, 8, "ok", older)], dag.SUMMARIES_SCHEMA)
    llm = _FakeLLM([_answer()])
    monkeypatch.setattr(dag, "gateway_client", lambda partition_key: llm)
    monkeypatch.setattr("products.signals.dags.inbox_ranking.training.telemetry.is_cloud", lambda: True)
    monkeypatch.setattr(
        "products.signals.dags.inbox_ranking.training.telemetry.get_client", lambda region, **kwargs: _FailingCapture()
    )

    for _ in range(2):
        dag.activity_summaries(dagster.build_asset_context(partition_key=PARTITION), dag.SummariesConfig())

    rows = memory_s3.read(dag.SUMMARIES_TABLE, PARTITION)
    assert [(row["user_id"], row["status"], row["used_previous_summary"]) for row in rows] == [
        (7, "ok", True),
        (8, "ok", False),
    ]
    messages = {
        req["messages"][1]["content"].rsplit("\n", 1)[-1]: req["messages"][1]["content"] for req in llm.requests
    }
    assert "Builds the signup funnel." in messages["- input seven"]
    assert "Previous summary:\nNone" in messages["- input eight"]


class _FailingForLLM(_FakeLLM):
    def __init__(self, failing_input: str):
        super().__init__([_answer()])
        self.failing_input = failing_input

    def create(self, **kwargs: Any) -> SimpleNamespace:
        if kwargs["messages"][1]["content"].endswith(self.failing_input):
            self.requests.append(kwargs)
            raise _CONNECTION_ERROR
        return super().create(**kwargs)


@pytest.mark.parametrize("users", [[7], [7, 8]], ids=["every row fails", "one row fails"])
def test_summaries_asset_keeps_earlier_successes_when_a_rerun_fails(
    users: list[int], memory_s3: _MemoryS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = {7: "seven", 8: "eight"}
    memory_s3.write(
        dag.INPUTS_TABLE,
        PARTITION,
        [_input_row(2, user, f"- input {names[user]}") for user in users],
        dag.INPUTS_SCHEMA,
    )
    memory_s3.write(dag.SUMMARIES_TABLE, PARTITION, [_summary_row(2, 7, "ok", PREVIOUS)], dag.SUMMARIES_SCHEMA)
    monkeypatch.setattr(dag, "gateway_client", lambda partition_key: _FailingForLLM("- input seven"))
    context = dagster.build_asset_context(partition_key=PARTITION)

    if len(users) == 1:
        with pytest.raises(dagster.Failure):
            dag.activity_summaries(context, dag.SummariesConfig())
    else:
        dag.activity_summaries(context, dag.SummariesConfig())

    rows = memory_s3.read(dag.SUMMARIES_TABLE, PARTITION)
    assert [(row["user_id"], row["status"]) for row in rows] == [(user, "ok") for user in users]
    assert rows[0]["summary_json"] == json.dumps(PREVIOUS)


@parameterized.expand(
    [
        ("recent partition", "2026-10-18", True),
        ("at the cutoff", "2026-07-29", True),
        ("past the cutoff", "2026-07-28", False),
    ]
)
def test_within_source_ttl(_name: str, partition_key: str, expected: bool) -> None:
    assert within_source_ttl(partition_key, datetime.date(2026, 10, 19)) is expected


@time_machine.travel(datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC), tick=False)
def test_embeddings_asset_embeds_only_new_text_and_never_shrinks_a_written_partition(
    memory_s3: _MemoryS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = {"summary": "Builds the signup funnel.", "focus_areas": [], "products": []}
    memory_s3.write(
        dag.SUMMARIES_TABLE,
        PARTITION,
        [_summary_row(2, 7, "ok", current), _summary_row(2, 8, "ok", current), _summary_row(2, 9, "failed", None)],
        dag.SUMMARIES_SCHEMA,
    )
    vector = [0.5] * 4
    store = {
        SummaryDocument(team_id=2, document_id=f"7:{PARTITION}"): LandedVector(
            embedding=vector, content=summary_text(current)
        ),
        SummaryDocument(team_id=2, document_id=f"8:{PARTITION}"): LandedVector(
            embedding=vector, content="text before a re-run"
        ),
    }
    emitted: list[tuple[int, str]] = []

    def emit(
        *, team_id: int, user_id: int, partition_key: str, prompt_version: int, text: str, day_start: datetime.datetime
    ) -> None:
        emitted.append((user_id, text))
        store[SummaryDocument(team_id=team_id, document_id=f"{user_id}:{partition_key}")] = LandedVector(
            embedding=vector, content=text
        )

    monkeypatch.setattr(dag, "emit_summary_embedding", emit)
    monkeypatch.setattr(dag, "flush_embedding_requests", lambda: None)
    monkeypatch.setattr(dag.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        dag, "landed_vectors", lambda documents, day_start: {d: store[d] for d in documents if d in store}
    )

    dag.activity_summary_embeddings(dagster.build_asset_context(partition_key=PARTITION), dag.SummaryEmbeddingsConfig())

    assert emitted == [(8, summary_text(current))]
    rows = memory_s3.read(dag.SUMMARY_EMBEDDINGS_TABLE, PARTITION)
    assert [row["user_id"] for row in rows] == [7, 8]
    assert set(rows[0]) == set(dag.SUMMARY_EMBEDDINGS_SCHEMA.names)

    store.clear()
    monkeypatch.setattr(dag, "emit_summary_embedding", lambda **kwargs: None)
    dag.activity_summary_embeddings(
        dagster.build_asset_context(partition_key=PARTITION), dag.SummaryEmbeddingsConfig(wait_seconds=0)
    )
    assert [row["user_id"] for row in memory_s3.read(dag.SUMMARY_EMBEDDINGS_TABLE, PARTITION)] == [7, 8]
