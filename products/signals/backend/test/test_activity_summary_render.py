import json
import datetime
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest

from openai import APIConnectionError
from parameterized import parameterized

from products.signals.backend.activity_summary.prompt import (
    MAX_PRODUCT_CHARS,
    MAX_RECENT_SHIFT_CHARS,
    MAX_TOPIC_CHARS,
    MalformedSummaryError,
    normalize_summary,
    summary_text,
    user_message,
)
from products.signals.backend.activity_summary.render import (
    ACTIVITY_HEADER,
    ACTIVITY_LINE_CHARS,
    ACTIVITY_LINES,
    MAX_UNITS_PER_DAY,
    SECTIONS_MAX_CHARS,
    TASK_LINE_CHARS,
    TASK_LINES,
    TASKS_HEADER,
    ActivityItem,
    Drop,
    TaskItem,
    Unit,
    activity_units,
    build_input,
    burst_cap,
    clean_text,
    sample_units,
    sampling_seed,
    task_units,
)
from products.signals.backend.activity_summary.summaries import (
    MAX_COMPLETION_TOKENS,
    PIPELINE_DISTINCT_ID,
    SummaryPrices,
    cost_usd,
    summarize,
)

AS_OF = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)
PATH_SECRET = "https://hooks.example.com/services/T000/B000/s3cr3tPathValue?sig=abc"


def _at(days_ago: float, minutes: int = 0) -> datetime.datetime:
    return AS_OF - datetime.timedelta(days=days_ago) + datetime.timedelta(minutes=minutes)


def _task(title: str, summary: str | None = None, tags: tuple[str, ...] = (), days_ago: float = 1) -> TaskItem:
    return TaskItem(at=_at(days_ago), title=title, summary=summary, tags=tags)


def _change(
    scope: str,
    activity: str,
    name: str | None,
    client: str | None = None,
    days_ago: float = 1,
    intent: str | None = None,
) -> ActivityItem:
    return ActivityItem(at=_at(days_ago), scope=scope, activity=activity, name=name, client=client, intent=intent)


@parameterized.expand(
    [
        (
            "a summary gives the goal, without its label, and the tags",
            _task("why", summary="Goal: find why weekly signups dropped. Done: found a broken form.", tags=("growth",)),
            "- 2026-10-18 [growth] find why weekly signups dropped. Done: found a broken form.",
            {},
        ),
        (
            "a link in a summary keeps only its host",
            _task("why", summary=f"Goal: post the alert to {PATH_SECRET} for the team."),
            "- 2026-10-18 post the alert to [link hooks.example.com] for the team.",
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


@parameterized.expand(
    [
        ("no intent renders as before", [None], '- 2026-10-18 updated Insight "Signup funnel"'),
        (
            "an intent renders next to the object",
            ["Split the funnel by plan"],
            '- 2026-10-18 updated Insight "Signup funnel" (agent: Split the funnel by plan)',
        ),
        (
            "collapsed rows carry the newest intent",
            ["Add a breakdown", None, "Split the funnel by plan"],
            '- 2026-10-18 updated Insight "Signup funnel" (x3) (agent: Add a breakdown)',
        ),
        (
            "an intent keeps only the host of a link",
            [f"Send the funnel to {PATH_SECRET}"],
            '- 2026-10-18 updated Insight "Signup funnel" (agent: Send the funnel to [link hooks.example.com])',
        ),
    ]
)
def test_activity_units_render_the_agent_intent(_name: str, intents: list[str | None], expected: str) -> None:
    items = [
        _change("Insight", "updated", "Signup funnel", days_ago=1 + index * 0.01, intent=intent)
        for index, intent in enumerate(intents)
    ]
    assert [unit.text for unit in activity_units(items, Counter())] == [expected]


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
            "a url keeps only its host, without its path or query",
            "Open https://example.com/insights/abc?token=xyz&a=1 now",
            "Open [link example.com] now",
        ),
        ("a secret in a url path is gone", f"See {PATH_SECRET}", "See [link hooks.example.com]"),
        ("an angle-bracketed slack link", "See <https://example.com/a/b> now", "See [link example.com] now"),
        ("credentials in a url are gone", "Use https://user:pass@db.example.com/x", "Use [link db.example.com]"),
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

    first = sample_units(units, limit=TASK_LINES, as_of=AS_OF, seed=seed)
    assert first == sample_units(list(reversed(units)), limit=TASK_LINES, as_of=AS_OF, seed=seed)
    assert len(first) == TASK_LINES
    assert first == sorted(first, key=lambda unit: unit.at)

    picked_ages = [
        (AS_OF - unit.at).days
        for partition in range(50)
        for unit in sample_units(units, limit=TASK_LINES, as_of=AS_OF, seed=sampling_seed(str(partition), 2, 7))
    ]
    assert sum(1 for age in picked_ages if age < 7) > sum(1 for age in picked_ages if age >= 21)


def test_build_input_renders_the_two_sections_in_order() -> None:
    rendered = build_input(
        [_task("why", summary="Asked: why did signups drop?", tags=("growth",), days_ago=3)],
        [_change("Dashboard", "created", "Growth overview", days_ago=1)],
        as_of=AS_OF,
        seed=1,
    )

    assert rendered is not None
    assert rendered.text == "\n".join(
        [
            TASKS_HEADER,
            "- 2026-10-16 [growth] why did signups drop?",
            "",
            ACTIVITY_HEADER,
            '- 2026-10-18 created Dashboard "Growth overview"',
        ]
    )
    assert (rendered.n_tasks, rendered.n_activity_lines, rendered.units) == (1, 1, 2)
    assert rendered.input_chars == len(rendered.text)
    assert build_input([_task("root cause")], [], as_of=AS_OF, seed=1) is None


def test_build_input_stays_inside_its_bounds_for_a_very_active_person() -> None:
    runaway = "word " * 2000
    tasks = [
        _task(runaway, summary=f"{day} {n} {runaway}", tags=(runaway,) * 20, days_ago=day + 0.01 * n)
        for day in range(28)
        for n in range(20)
    ]
    activity = [_change("Insight", "created", f"{runaway} {n}", days_ago=n % 28, intent=runaway) for n in range(500)]

    rendered = build_input(tasks, activity, as_of=AS_OF, seed=1)

    assert rendered is not None
    assert (rendered.n_tasks, rendered.n_activity_lines) == (TASK_LINES, ACTIVITY_LINES)
    tasks_text, activity_text = rendered.text.split("\n\n")
    assert max(len(line) for line in tasks_text.split("\n")[1:]) <= TASK_LINE_CHARS
    assert max(len(line) for line in activity_text.split("\n")[1:]) <= ACTIVITY_LINE_CHARS
    assert rendered.input_chars <= SECTIONS_MAX_CHARS
    assert rendered.drops[Drop.BURST_CAP] > 0 and rendered.drops[Drop.SAMPLE_CAP] > 0


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
        (
            "topic, product and recent_shift are cut to their caps",
            _answer(
                focus_areas=[{"topic": "t" * 500, "strength": "high", "last_seen": "2026-10-17"}],
                products=["p" * 500],
                recent_shift="s" * 2000,
            ),
            True,
            {
                "focus_areas": [{"topic": "t" * MAX_TOPIC_CHARS, "strength": "high", "last_seen": "2026-10-17"}],
                "products": ["p" * MAX_PRODUCT_CHARS],
                "recent_shift": "s" * MAX_RECENT_SHIFT_CHARS,
            },
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


_PRICES = SummaryPrices(input_price_per_million_tokens=0.1, output_price_per_million_tokens=0.5)


@parameterized.expand(
    [
        ("both prices", 1_000_000, 200_000, _PRICES, 0.2),
        ("unknown usage", None, None, _PRICES, None),
        (
            "no output price",
            1_000,
            100,
            SummaryPrices(input_price_per_million_tokens=0.1, output_price_per_million_tokens=None),
            None,
        ),
        ("a model with no prices", 1_000, 100, None, None),
    ]
)
def test_cost_usd(
    _name: str, tokens_in: int | None, tokens_out: int | None, prices: SummaryPrices | None, expected: float | None
) -> None:
    assert cost_usd(tokens_in, tokens_out, prices) == (pytest.approx(expected) if expected is not None else None)


class FakeLLM:
    """Answers are a JSON string, `(content, finish_reason)`, or an exception to raise."""

    def __init__(self, answers: list[Any], *, usage: bool = True):
        self.answers = list(answers)
        self.usage = usage
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        content, finish_reason = answer if isinstance(answer, tuple) else (answer, "stop")
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20) if self.usage else None,
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)],
        )


_CONNECTION_ERROR = APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]


@parameterized.expand(
    [
        ("a malformed answer is retried once", ["not json", _answer()], True, 2, None, (200, 40)),
        (
            "two malformed answers fail",
            ["not json", "still not json"],
            False,
            2,
            "malformed_output: response is not JSON",
            (200, 40),
        ),
        (
            "a truncated answer is retried, then fails",
            [(_answer(), "length")],
            False,
            2,
            "malformed_output: response was truncated",
            (200, 40),
        ),
        ("a truncated answer then a full one succeeds", [(_answer(), "length"), _answer()], True, 2, None, (200, 40)),
        (
            "a failed request fails without a retry, with unknown usage",
            [_CONNECTION_ERROR],
            False,
            1,
            "api_error: APIConnectionError",
            (None, None),
        ),
    ]
)
def test_summarize_retries_a_malformed_or_truncated_answer_once(
    _name: str,
    answers: list[Any],
    succeeds: bool,
    attempts: int,
    error: str | None,
    tokens: tuple[int | None, int | None],
) -> None:
    llm = FakeLLM(answers)
    outcome = summarize(
        llm,  # type: ignore[arg-type]
        rendered_input="- a line",
        previous_summary=None,
        model="gpt-6-luna",
        as_of=datetime.date(2026, 10, 18),
    )

    assert len(llm.requests) == attempts
    assert {req["user"] for req in llm.requests} == {PIPELINE_DISTINCT_ID}
    assert {req["max_completion_tokens"] for req in llm.requests} == {MAX_COMPLETION_TOKENS}
    assert (outcome.summary is not None, outcome.error) == (succeeds, error)
    assert (outcome.tokens_in, outcome.tokens_out) == tokens


def test_summarize_reports_null_tokens_when_the_response_has_no_usage() -> None:
    outcome = summarize(
        FakeLLM([_answer()], usage=False),  # type: ignore[arg-type]
        rendered_input="- a line",
        previous_summary=None,
        model="gpt-6-luna",
        as_of=datetime.date(2026, 10, 18),
    )
    assert outcome.summary is not None
    assert (outcome.tokens_in, outcome.tokens_out) == (None, None)
