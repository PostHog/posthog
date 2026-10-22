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
    DEFAULT_LIMITS,
    MAX_ACTIVITY_LINES_PER_DAY,
    MAX_COMPLETION_TOKENS,
    MAX_UNITS_PER_DAY,
    TASK_LINES,
    TASKS_HEADER,
    VIEWS_HEADER,
    ActivityItem,
    Drop,
    Parent,
    RenderLimits,
    TaskItem,
    Unit,
    ViewItem,
    activity_units,
    build_input,
    burst_cap,
    clean_text,
    sample_units,
    sampling_seed,
    task_units,
    view_units,
)
from products.signals.backend.activity_summary.summaries import PIPELINE_DISTINCT_ID, SummaryPrices, cost_usd, summarize

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
    item_id: str | None = None,
) -> ActivityItem:
    return ActivityItem(
        at=_at(days_ago), scope=scope, activity=activity, name=name, client=client, intent=intent, item_id=item_id
    )


QUALITY = Parent(scope="Dashboard", item_id="10", name="Quality review")
GROWTH = Parent(scope="Dashboard", item_id="11", name="Growth overview")


def _view(
    view_type: str, ref: str, name: str | None = None, days: int = 1, days_ago: float = 1, not_theirs: bool = False
) -> ViewItem:
    opened = tuple(sorted(_at(days_ago + n).date() for n in range(days)))
    return ViewItem(at=_at(days_ago), type=view_type, ref=ref, name=name, days=opened, not_theirs=not_theirs)


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


@parameterized.expand(
    [
        (
            "insights on one dashboard merge with the dashboard's created row",
            [
                _change("Dashboard", "created", "Quality review", days_ago=3, item_id="10"),
                _change("Insight", "created", "Records judged per day", days_ago=2.9, item_id="1"),
                _change("Insight", "created", "Suggestion defect rates", days_ago=2.8, item_id="2"),
                _change("Insight", "updated", "Suggestion defect rates", days_ago=2.7, item_id="2"),
                _change("Insight", "created", "Unplaced funnel", days_ago=1, item_id="3"),
            ],
            {("Insight", "1"): (QUALITY,), ("Insight", "2"): (QUALITY,)},
            [
                '- 2026-10-16 created Dashboard "Quality review" with 2 Insights: '
                '"Suggestion defect rates", "Records judged per day"',
                '- 2026-10-18 created Insight "Unplaced funnel"',
            ],
            {Drop.GROUPED_INTO_PARENT: 3},
        ),
        (
            "insights on a dashboard the person did not create group under it",
            [
                _change("Insight", "created", "Records judged per day", item_id="1"),
                _change("Insight", "updated", "Suggestion defect rates", item_id="2"),
            ],
            {("Insight", "1"): (QUALITY,), ("Insight", "2"): (QUALITY,)},
            [
                '- 2026-10-18 created and updated 2 Insights on Dashboard "Quality review": '
                '"Records judged per day", "Suggestion defect rates"'
            ],
            {Drop.GROUPED_INTO_PARENT: 1},
        ),
        (
            "a lone insight names its dashboard and how many more it sits on",
            [_change("Insight", "created", "Signup funnel", item_id="1")],
            {("Insight", "1"): (GROWTH, QUALITY)},
            ['- 2026-10-18 created Insight "Signup funnel" on Dashboard "Growth overview" (+1 more)'],
            {},
        ),
        (
            "an insight joins the dashboard that holds the other changed insights",
            [
                _change("Insight", "created", "Signup funnel", item_id="1"),
                _change("Insight", "created", "Defect rates", item_id="2"),
            ],
            {("Insight", "1"): (GROWTH, QUALITY), ("Insight", "2"): (QUALITY,)},
            ['- 2026-10-18 created 2 Insights on Dashboard "Quality review": "Defect rates", "Signup funnel"'],
            {Drop.GROUPED_INTO_PARENT: 1},
        ),
        (
            "an auto-named dashboard gives no context",
            [_change("Insight", "created", "Signup funnel", item_id="1")],
            {("Insight", "1"): (Parent(scope="Dashboard", item_id="12", name="Daily report 2026-10-18"),)},
            ['- 2026-10-18 created Insight "Signup funnel"'],
            {},
        ),
    ]
)
def test_activity_units_group_children_under_their_parent(
    _name: str,
    items: list[ActivityItem],
    parents: dict[tuple[str, str], tuple[Parent, ...]],
    expected: list[str],
    expected_drops: dict[str, int],
) -> None:
    drops: Counter[str] = Counter()
    assert [unit.text for unit in activity_units(items, drops, parents)] == expected
    assert dict(drops) == expected_drops


def test_a_group_line_lists_the_names_that_fit_and_marks_the_rest() -> None:
    items = [
        _change(
            "Insight", "created", f"Insight number {n} with a fairly long name", days_ago=1 + n / 100, item_id=str(n)
        )
        for n in range(12)
    ]
    parents = {("Insight", str(n)): (QUALITY,) for n in range(12)}

    [unit] = activity_units(items, Counter(), parents)

    assert unit.text.startswith('- 2026-10-18 created 12 Insights on Dashboard "Quality review": "Insight number 0')
    assert unit.text.endswith('", …')
    assert len(unit.text) <= ACTIVITY_LINE_CHARS


@parameterized.expand(
    [
        ("other days take the slots a burst would fill", 12, MAX_ACTIVITY_LINES_PER_DAY),
        ("a burst fills the slots no other day takes", 3, ACTIVITY_LINES - 3),
        ("a lone busy day still fills the section", 0, ACTIVITY_LINES),
    ]
)
def test_activity_units_spread_a_burst_across_days(_name: str, older_days: int, expected_burst_lines: int) -> None:
    drops: Counter[str] = Counter()
    burst = [_change("Insight", "created", f"Burst {n}", days_ago=1 - n / 1000) for n in range(ACTIVITY_LINES + 5)]
    older = [_change("Notebook", "updated", f"Older {day}", days_ago=day) for day in range(2, 2 + older_days)]

    units = activity_units(burst + older, drops)

    assert len(units) == ACTIVITY_LINES
    assert sum(1 for unit in units if "Burst" in unit.text) == expected_burst_lines
    assert drops[Drop.BURST_CAP] + drops[Drop.SAMPLE_CAP] == len(burst) + len(older) - ACTIVITY_LINES


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


def test_build_input_renders_the_three_sections_in_order() -> None:
    rendered = build_input(
        [_task("why", summary="Asked: why did signups drop?", tags=("growth",), days_ago=3)],
        [_change("Dashboard", "created", "Growth overview", days_ago=1)],
        as_of=AS_OF,
        seed=1,
        views=[
            _view("insight", "abc", "Weekly signups", days_ago=1),
            _view("dashboard", "9", "Growth overview", days=3, days_ago=2),
        ],
    )

    assert rendered is not None
    assert rendered.text == "\n".join(
        [
            TASKS_HEADER,
            "- 2026-10-16 [growth] why did signups drop?",
            "",
            ACTIVITY_HEADER,
            '- 2026-10-18 created Dashboard "Growth overview"',
            "",
            VIEWS_HEADER,
            '- Dashboard "Growth overview": opened 3 days, last 2026-10-17, edited 1 day',
            '- Insight "Weekly signups": opened 1 day, last 2026-10-18',
        ]
    )
    assert (rendered.n_tasks, rendered.n_activity_lines, rendered.n_view_lines, rendered.units) == (1, 1, 2, 4)
    assert rendered.input_chars == len(rendered.text)
    assert build_input([_task("root cause")], [], as_of=AS_OF, seed=1) is None
    assert build_input([], [], as_of=AS_OF, seed=1, views=[_view("scene", "Settings")]) is None


def test_view_units_name_products_count_edits_and_drop_what_says_nothing() -> None:
    drops: Counter[str] = Counter()
    views = [
        _view("scene", "ErrorTrackingIssue", days=2),
        _view("scene", "ErrorTracking", days=3, days_ago=2),
        _view("scene", "Settings"),
        _view("scene", "ProjectHomepage"),
        _view("insight", "abc", "Weekly signups", days=5, not_theirs=True),
        _view("feature_flag", "7", "new-checkout", days=2),
        _view("notebook", "n1", "Daily report 2026-10-18"),
        _view("dashboard", "9", None),
    ]
    activity = [
        _change("FeatureFlag", "updated", "new-checkout", days_ago=1),
        _change("FeatureFlag", "updated", "new-checkout", days_ago=1.5),
        _change("FeatureFlag", "updated", "new-checkout", days_ago=3, client="scout:feature-flags"),
    ]

    units = view_units(views, activity, drops)

    assert sorted(unit.text for unit in units) == [
        "- Error tracking pages: opened 4 days, last 2026-10-18",
        '- Feature flag "new-checkout": opened 2 days, last 2026-10-18, edited 2 days',
        '- Insight "Weekly signups": opened 5 days, last 2026-10-18, not theirs',
    ]
    assert dict(drops) == {Drop.GENERIC_SCENE: 2, Drop.AUTO_NAMED_OBJECT: 1, Drop.UNNAMED_OBJECT: 1}


@parameterized.expand(
    [
        ("default limits", DEFAULT_LIMITS),
        (
            "limits from the flag",
            RenderLimits(
                task_lines=5,
                activity_lines=30,
                max_units_per_day=1,
                sections_max_chars=20000,
                task_line_chars=240,
                activity_line_chars=400,
            ),
        ),
    ]
)
def test_build_input_stays_inside_its_bounds_for_a_very_active_person(_name: str, limits: RenderLimits) -> None:
    runaway = "word " * 2000
    tasks = [
        _task(runaway, summary=f"{day} {n} {runaway}", tags=(runaway,) * 20, days_ago=day + 0.01 * n)
        for day in range(28)
        for n in range(20)
    ]
    activity = [_change("Insight", "created", f"{runaway} {n}", days_ago=n % 28, intent=runaway) for n in range(500)]

    rendered = build_input(tasks, activity, as_of=AS_OF, seed=1, limits=limits)

    assert rendered is not None
    assert (rendered.n_tasks, rendered.n_activity_lines) == (limits.task_lines, limits.activity_lines)
    tasks_text, activity_text = rendered.text.split("\n\n")
    assert max(len(line) for line in tasks_text.split("\n")[1:]) <= limits.task_line_chars
    assert max(len(line) for line in activity_text.split("\n")[1:]) <= limits.activity_line_chars
    assert rendered.input_chars <= limits.sections_max_chars
    assert rendered.drops[Drop.BURST_CAP] > 0 and rendered.drops[Drop.SAMPLE_CAP] > 0


def test_build_input_drops_every_unit_for_a_budget_below_the_section_overhead() -> None:
    rendered = build_input(
        [_task("why", summary="Asked: why did signups drop?", days_ago=3)],
        [_change("Dashboard", "created", "Growth overview", days_ago=1)],
        as_of=AS_OF,
        seed=1,
        limits=RenderLimits(sections_max_chars=1),
    )

    assert rendered is not None
    assert (rendered.text, rendered.units, rendered.drops[Drop.SECTIONS_BUDGET]) == ("", 0, 2)


PREVIOUS = {
    "profile": "## Funnels\n- Builds the signup funnel.",
    "headline": "Builds the signup funnel.",
    "focus_areas": [],
    "products": ["product_analytics"],
    "recent_shift": "Moved from flags to funnels.",
}
PREVIOUS_BEFORE_PROFILES = {"summary": "Builds the signup funnel.", "focus_areas": [], "products": []}


@parameterized.expand(
    [
        (
            "with a previous summary",
            PREVIOUS,
            ["## Funnels\\n- Builds the signup funnel.", "Builds the signup funnel."],
        ),
        ("with a summary from before profiles", PREVIOUS_BEFORE_PROFILES, ['"headline": "Builds the signup funnel."']),
        ("cold start", None, ["Previous summary:\nNone"]),
    ]
)
def test_user_message_sends_only_the_rendered_input_and_the_previous_summary(
    _name: str, previous: dict[str, Any] | None, expected: list[str]
) -> None:
    message = user_message("- 2026-10-17 Build a funnel", previous, datetime.date(2026, 10, 18))
    assert message.startswith("Today is 2026-10-18.")
    assert message.endswith("Recent activity:\n- 2026-10-17 Build a funnel")
    assert all(text in message for text in expected)
    assert "Moved from flags" not in message


def _answer(**overrides: Any) -> str:
    return json.dumps(
        {
            "profile": "## Funnels\n- Builds the signup funnel.",
            "headline": "Builds the signup funnel.",
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
            "a long profile keeps its line breaks and is cut at a word boundary",
            _answer(profile="## Funnels\n" + "word " * 2000),
            False,
            {"profile": "## Funnels\n" + " ".join(["word"] * 1197) + "…"},
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
            "topic, product and recent_shift are cut at a word boundary inside their caps",
            _answer(
                focus_areas=[{"topic": "adoption " * 50, "strength": "high", "last_seen": "2026-10-17"}],
                products=["analytics " * 50],
                recent_shift="shift " * 400,
            ),
            True,
            {
                "focus_areas": [
                    {
                        "topic": " ".join(["adoption"] * ((MAX_TOPIC_CHARS - 1) // 9)) + "…",
                        "strength": "high",
                        "last_seen": "2026-10-17",
                    }
                ],
                "products": [" ".join(["analytics"] * ((MAX_PRODUCT_CHARS - 1) // 10)) + "…"],
                "recent_shift": " ".join(["shift"] * ((MAX_RECENT_SHIFT_CHARS - 1) // 6)) + "…",
            },
        ),
        (
            "one long word is cut and marked",
            _answer(products=["p" * 500]),
            False,
            {"products": ["p" * (MAX_PRODUCT_CHARS - 1) + "…"]},
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
        ("no profile", _answer(profile="  ")),
        ("no headline", _answer(headline=None)),
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


def test_summarize_cuts_a_previous_profile_to_a_lowered_limit() -> None:
    stored_profile = "## Funnels\n" + "Builds the signup funnel. " * 230
    assert len(stored_profile) > 5000
    llm = FakeLLM([_answer()])

    summarize(
        llm,  # type: ignore[arg-type]
        rendered_input="- a line",
        previous_summary={**PREVIOUS, "profile": stored_profile},
        model="gpt-6-luna",
        as_of=datetime.date(2026, 10, 18),
        profile_max_chars=500,
    )

    user_turn = llm.requests[0]["messages"][1]["content"]
    previous = json.loads(user_turn.split("Previous summary:\n", 1)[1].split("\n\nRecent activity:", 1)[0])
    assert len(previous["profile"]) <= 500
    assert previous["profile"].startswith("## Funnels\nBuilds the signup funnel.")
