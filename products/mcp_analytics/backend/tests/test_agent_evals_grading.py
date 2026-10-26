import json
import asyncio
import tempfile
from collections.abc import Mapping
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

import anthropic
from anthropic.types import Message, StopReason, TextBlock, Usage
from parameterized import parameterized

from posthog.llm.system_one import JsonValue, NoulAnswer, Question, RefusalAnswer, SystemOneResult
from posthog.llm.system_one_client import SystemOneClient

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial, ToolCallRecord, TrialUsage
from products.mcp_analytics.backend.agent_evals.grading import (
    GradedReport,
    Grader,
    Judgment,
    TrialGrade,
    Verdict,
    called_tools,
    expected_tools_grader,
    format_grade_summary,
    grade_trial,
)
from products.mcp_analytics.backend.agent_evals.model_graders import make_jev, make_judge
from products.mcp_analytics.backend.agent_evals.runner import AgentRunReport
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

SCENARIO = Scenario(
    id="flags-list-active",
    intent="List all our active feature flags.",
    success_criteria="Returns the active flags by key.",
    expected_tools=("feature-flag-get-all",),
)


def _call(name: str, tool_input: object = None, is_error: bool = False) -> ToolCallRecord:
    return ToolCallRecord(name=name, input=tool_input or {}, is_error=is_error, result_text="SECRET", latency_ms=1)


def _exec(command: object, is_error: bool = False) -> ToolCallRecord:
    return _call("exec", {"command": command}, is_error)


def _trial(
    calls: tuple[ToolCallRecord, ...] = (), outcome: str = "answered", scenario_id: str = SCENARIO.id
) -> AgentTrial:
    return AgentTrial(
        scenario_id=scenario_id,
        trial=1,
        outcome=outcome,  # type: ignore[arg-type]
        final_text="Two flags.",
        tool_calls=calls,
        turns=2,
        usage=TrialUsage(),
        duration_ms=3,
    )


class TestCalledTools(SimpleTestCase):
    @parameterized.expand(
        [
            ("exec_call_is_the_inner_tool", _exec("call feature-flag-get-all {}"), {"feature-flag-get-all"}),
            ("server_flags_are_stripped", _exec("call --json --confirm flag-delete {}"), {"flag-delete"}),
            ("an_unknown_flag_is_the_target_like_on_the_server", _exec("call --foo flag-x"), {"--foo"}),
            ("a_failed_attempt_still_counts", _exec("call flag-delete {}", is_error=True), {"flag-delete"}),
            ("info_names_no_tool", _exec("info feature-flag-get-all"), set()),
            ("call_without_a_tool_names_none", _exec("call --json"), set()),
            ("non_string_command_names_none", _exec(42), set()),
            ("a_tab_is_not_a_separator_on_the_server", _exec("call\tflag-x {}"), set()),
            ("a_control_character_js_trim_keeps_stays_in_the_verb", _exec("\x1ccall flag-x"), set()),
            ("a_newline_stays_in_the_tool_token", _exec("call flag-x\n{}"), {"flag-x\n{}"}),
            ("a_direct_tool_is_itself", _call("feature-flag-get-all"), {"feature-flag-get-all"}),
        ]
    )
    def test_called_tools(self, _name: str, call: ToolCallRecord, expected: set[str]) -> None:
        assert called_tools(_trial((call,))) == expected


class TestExpectedTools(SimpleTestCase):
    @parameterized.expand(
        [
            ("called", SCENARIO, (_exec("call feature-flag-get-all {}"),), Judgment(passed=True, score=1.0, rationale="every expected tool was called")),
            ("only_described", SCENARIO, (_exec("info feature-flag-get-all"),), Judgment(passed=False, score=0.0, rationale="missing tools: feature-flag-get-all")),
            ("no_expectation", SCENARIO.model_copy(update={"expected_tools": ()}), (), Judgment(passed=None, score=None, rationale="scenario lists no expected tools")),
        ]
    )  # fmt: skip
    def test_judgment(
        self, _name: str, scenario: Scenario, calls: tuple[ToolCallRecord, ...], expected: Judgment
    ) -> None:
        assert asyncio.run(expected_tools_grader(scenario, _trial(calls))) == expected


async def _passing(scenario: Scenario, trial: AgentTrial) -> Judgment:
    return Judgment(passed=True, score=1.0, rationale="ok")


async def _crashing(scenario: Scenario, trial: AgentTrial) -> Judgment:
    raise TimeoutError("read timed out")


class TestGradeTrial(SimpleTestCase):
    @parameterized.expand(
        [
            ("answered_reaches_the_grader", "answered", Verdict(grader="g", passed=True, score=1.0, rationale="ok")),
            ("mcp_error_is_not_gradable", "mcp_error", Verdict(grader="g", passed=None, score=None, rationale="mcp_error: infrastructure failure")),
            ("turn_limit_fails", "turn_limit", Verdict(grader="g", passed=False, score=None, rationale="turn_limit")),
        ]
    )  # fmt: skip
    def test_outcome_gate(self, _name: str, outcome: str, expected: Verdict) -> None:
        grade = asyncio.run(grade_trial(SCENARIO, _trial(outcome=outcome), {"g": _passing}))

        assert grade.verdicts == (expected,)

    def test_a_crashing_grader_becomes_an_error_verdict_and_the_others_still_count(self) -> None:
        grade = asyncio.run(grade_trial(SCENARIO, _trial(), {"ok": _passing, "boom": _crashing}))

        assert grade.verdicts == (
            Verdict(grader="ok", passed=True, score=1.0, rationale="ok"),
            Verdict(
                grader="boom", passed=None, score=None, rationale="grader failed", error="TimeoutError: read timed out"
            ),
        )


class _FakeMessages:
    def __init__(self, response: Message) -> None:
        self.response = response
        self.sent: dict[str, Any] = {}

    async def create(self, **kwargs: object) -> Message:
        self.sent = kwargs
        return self.response


def _judge_reply(text: str, stop_reason: StopReason = "end_turn") -> Message:
    return Message.model_construct(
        id="m", type="message", role="assistant", model="claude-sonnet-5-5", content=[TextBlock(type="text", text=text)],
        stop_reason=stop_reason, stop_sequence=None, usage=Usage(input_tokens=1, output_tokens=1),
    )  # fmt: skip


def _judge(messages: _FakeMessages) -> Grader:
    return make_judge(cast(anthropic.AsyncAnthropic, SimpleNamespace(messages=messages)), "claude-sonnet-5-5")


class TestJudge(SimpleTestCase):
    @parameterized.expand(
        [
            ("pass", '{"passed": true, "rationale": "Lists the keys."}', Judgment(passed=True, score=1.0, rationale="Lists the keys.", model="claude-sonnet-5-5")),
            ("fail", '{"passed": false, "rationale": "No keys."}', Judgment(passed=False, score=0.0, rationale="No keys.", model="claude-sonnet-5-5")),
        ]
    )  # fmt: skip
    def test_judgment(self, _name: str, reply: str, expected: Judgment) -> None:
        assert asyncio.run(_judge(_FakeMessages(_judge_reply(reply)))(SCENARIO, _trial())) == expected

    def test_a_reply_cut_short_is_a_grader_error_not_a_verdict(self) -> None:
        fake = _FakeMessages(_judge_reply('{"passed": true, "rationale": "ok"}', stop_reason="refusal"))

        grade = asyncio.run(grade_trial(SCENARIO, _trial(), {"judge": _judge(fake)}))

        assert [(v.passed, v.error) for v in grade.verdicts] == [(None, "ValueError: judge stopped with refusal")]

    def test_the_judge_sees_only_the_answer_as_user_input_and_replies_in_the_verdict_schema(self) -> None:
        fake = _FakeMessages(_judge_reply('{"passed": true, "rationale": "ok"}'))

        asyncio.run(_judge(fake)(SCENARIO, _trial((_exec("call x"),))))

        assert "tool_choice" not in fake.sent
        assert fake.sent["output_config"]["format"]["schema"]["required"] == ["passed", "rationale"]
        assert fake.sent["messages"] == [{"role": "user", "content": "Two flags."}]
        assert "<success_criteria>\nReturns the active flags by key.\n</success_criteria>" in fake.sent["system"]


class _FakeJev:
    def __init__(self, result: SystemOneResult) -> None:
        self.result = result
        self.sent: list[tuple[JsonValue, Mapping[str, Question]]] = []

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        self.sent.append((state, questions))
        return self.result


def _jev_result(answer: NoulAnswer | RefusalAnswer) -> SystemOneResult:
    return SystemOneResult(model="jev-1.13.0", answers={"passed": answer}, input_tokens=10)


class TestJev(SimpleTestCase):
    @parameterized.expand(
        [
            ("threshold_passes", NoulAnswer(probability=0.5), Judgment(passed=True, score=0.5, rationale="probability of success 0.50", model="jev-1.13.0")),
            ("low_probability_fails", NoulAnswer(probability=0.2), Judgment(passed=False, score=0.2, rationale="probability of success 0.20", model="jev-1.13.0")),
            ("refusal_is_not_gradable", RefusalAnswer(), Judgment(passed=None, score=None, rationale="declined to answer", model="jev-1.13.0")),
        ]
    )  # fmt: skip
    def test_judgment(self, _name: str, answer: NoulAnswer | RefusalAnswer, expected: Judgment) -> None:
        grader = make_jev(cast(SystemOneClient, _FakeJev(_jev_result(answer))))

        assert asyncio.run(grader(SCENARIO, _trial())) == expected

    def test_jev_receives_only_request_criteria_and_answer(self) -> None:
        fake = _FakeJev(_jev_result(NoulAnswer(probability=0.9)))

        asyncio.run(make_jev(cast(SystemOneClient, fake))(SCENARIO, _trial((_exec("call x"),))))

        [(state, questions)] = fake.sent
        assert state == {
            "request": "List all our active feature flags.",
            "success_criteria": "Returns the active flags by key.",
            "answer": "Two flags.",
        }
        assert list(questions) == ["passed"]
        assert "SECRET" not in repr(fake.sent)


def _grade(scenario_id: str, trial: int, outcome: str = "answered", **passed: bool | None | str) -> TrialGrade:
    verdicts = tuple(
        Verdict(grader=name, passed=None, score=None, rationale="grader failed", error=value)
        if isinstance(value, str)
        else Verdict(grader=name, passed=value, score=None, rationale="")
        for name, value in passed.items()
    )
    return TrialGrade(scenario_id=scenario_id, trial=trial, outcome=outcome, verdicts=verdicts)


class TestSummary(SimpleTestCase):
    def test_pass_rates_errors_and_disagreement_over_answered_trials_only(self) -> None:
        report = GradedReport(
            server_origin="u", model="m", effort="low", started_at="t",
            grader_models={"expected_tools": "deterministic", "judge": "claude-sonnet-5-5", "jev": "jev-latest"},
            grades=(
                _grade("a", 1, expected_tools=True, judge=True, jev=False),
                _grade("a", 2, expected_tools=False, judge=True, jev=True),
                _grade("b", 1, expected_tools=None, judge="TimeoutError: read timed out", jev=True),
                _grade("b", 2, "turn_limit", expected_tools=False, judge=False, jev=False),
            ),
        )  # fmt: skip

        assert format_grade_summary(report) == (
            "graded 4 trials with expected_tools, judge, jev\n"
            "  a: expected_tools 1/2, judge 2/2, jev 1/2\n"
            "  b: expected_tools 0/1, judge 0/1 (1 errors), jev 1/2\n"
            "judge and jev disagree on 1 of 2 trials both graded"
        )


def _report_json(scenario_id: str) -> str:
    trials = (
        _trial((_exec("call --json feature-flag-get-all {}"),), scenario_id=scenario_id),
        _trial(outcome="turn_limit", scenario_id=scenario_id),
    )
    return AgentRunReport(
        server_origin="http://x", header_names=(), tool_names=("exec",), scenarios=(SCENARIO,), model="m",
        effort="low", system_prompt="s", trials_per_scenario=1, max_turns=3, max_tokens=10, started_at="t0",
        finished_at="t1", trials=trials,
    ).to_json()  # fmt: skip


class TestGradeCommand(SimpleTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def _run(self, report_json: str, graders: str | None = None, out: str = "graded.json") -> tuple[str, str]:
        (self.directory / "run.json").write_text(report_json)
        stdout, stderr = StringIO(), StringIO()
        options: dict[str, object] = {"report": self.directory / "run.json", "out": self.directory / out}
        if graders is not None:
            options["graders"] = graders
        call_command("grade_mcp_evals", stdout=stdout, stderr=stderr, **options)
        return stdout.getvalue(), stderr.getvalue()

    def test_grades_a_saved_report_and_writes_json(self) -> None:
        summary, _ = self._run(_report_json(SCENARIO.id), "expected_tools")

        written = json.loads((self.directory / "graded.json").read_text())
        assert summary.splitlines()[:2] == [
            "graded 2 trials with expected_tools",
            "  flags-list-active: expected_tools 1/2",
        ]
        assert written["grader_models"] == {"expected_tools": "deterministic"}
        assert [(g["trial"], g["outcome"], [v["passed"] for v in g["verdicts"]]) for g in written["grades"]] == [
            (1, "answered", [True]),
            (1, "turn_limit", [False]),
        ]

    @parameterized.expand(
        [
            ("unknown_scenario", _report_json("gone"), "expected_tools", "graded.json", "trials for scenarios it does not record: gone"),
            ("unknown_grader", _report_json(SCENARIO.id), "expected_tools,bogus", "graded.json", "unknown graders: bogus"),
            ("not_a_report", '{"trials": []}', "expected_tools", "graded.json", "is not a run_mcp_evals report"),
            ("out_overwrites_report", _report_json(SCENARIO.id), "expected_tools", "run.json", "--out would overwrite the report"),
        ]
    )  # fmt: skip
    def test_bad_input_fails_before_grading(
        self, _name: str, report: str, graders: str, out: str, message: str
    ) -> None:
        with self.assertRaisesMessage(CommandError, message):
            self._run(report, graders, out)

    @override_settings(ANTHROPIC_API_KEY=None)
    def test_by_default_jev_stays_off_and_a_grader_without_credentials_is_skipped(self) -> None:
        _, stderr = self._run(_report_json(SCENARIO.id))

        written = json.loads((self.directory / "graded.json").read_text())
        assert stderr.strip() == "skipping grader judge: judge needs ANTHROPIC_API_KEY"
        assert written["grader_models"] == {"expected_tools": "deterministic"}
