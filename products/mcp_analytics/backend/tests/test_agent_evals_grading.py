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

import httpx
import anthropic
from anthropic.types import Message, TextBlock, Usage
from parameterized import parameterized

from posthog.llm.system_one import (
    JsonValue,
    NoulAnswer,
    Question,
    RefusalAnswer,
    SystemOneRequestFailed,
    SystemOneResult,
)
from posthog.llm.system_one_client import SystemOneClient

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial, ToolCallRecord, TrialUsage
from products.mcp_analytics.backend.agent_evals.grading import (
    EffectiveCall,
    GradedReport,
    Grader,
    TrialGrade,
    Verdict,
    effective_calls,
    expected_tools_grader,
    format_grade_summary,
    grade_trial,
    verdict,
)
from products.mcp_analytics.backend.agent_evals.model_graders import make_jev, make_judge
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

SCENARIO = Scenario(
    id="flags-list-active",
    intent="List all our active feature flags.",
    success_criteria="Returns the active flags by key.",
    expected_tools=("feature-flag-get-all",),
)


def _ec(verb: str, tool: str | None, is_error: bool) -> EffectiveCall:
    return EffectiveCall(verb=verb, tool=tool, is_error=is_error)


def _call(name: str, tool_input: object = None, is_error: bool = False) -> ToolCallRecord:
    return ToolCallRecord(name=name, input=tool_input or {}, is_error=is_error, result_text="SECRET", latency_ms=1)


def _exec(command: object, is_error: bool = False) -> ToolCallRecord:
    return _call("exec", {"command": command}, is_error)


def _trial(calls: tuple[ToolCallRecord, ...] = (), outcome: str = "answered") -> AgentTrial:
    return AgentTrial(
        scenario_id=SCENARIO.id, trial=1, outcome=outcome, final_text="Two flags.", tool_calls=calls,  # type: ignore[arg-type]
        turns=1, usage=TrialUsage(), duration_ms=5,
    )  # fmt: skip


class TestEffectiveCalls(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_call", _exec("call feature-flag-get-all"), _ec("call", "feature-flag-get-all", False)),
            ("call_json", _exec("call --json execute-sql {}"), _ec("call", "execute-sql", False)),
            (
                "call_confirm_json",
                _exec('call --confirm --json flag-delete {"id": 1}', is_error=True),
                _ec("call", "flag-delete", True),
            ),
            ("learn", _exec("learn"), _ec("learn", None, False)),
            ("info", _exec("info feature-flag-get-all"), _ec("info", None, False)),
            ("schema", _exec("schema execute-sql"), _ec("schema", None, False)),
            ("search", _exec("search flags"), _ec("search", None, False)),
            ("call_without_a_tool", _exec("call --json"), _ec("unknown", None, False)),
            ("empty_command", _exec(""), _ec("unknown", None, False)),
            ("input_not_an_object", _call("exec", "call x"), _ec("unknown", None, False)),
            ("direct_tool", _call("feature-flag-get-all"), _ec("call", "feature-flag-get-all", False)),
        ]
    )
    def test_effective_call(self, _name: str, record: ToolCallRecord, expected: EffectiveCall) -> None:
        assert effective_calls(_trial((record,))) == (expected,)


class TestOutcomeGate(SimpleTestCase):
    @parameterized.expand(
        [
            ("answered", True, "graded"),
            ("mcp_error", None, "mcp_error: infrastructure failure"),
            ("turn_limit", False, "turn_limit"),
            ("truncated", False, "truncated"),
            ("refused", False, "refused"),
            ("model_error", False, "model_error"),
        ]
    )
    def test_gate(self, outcome: str, passed: bool | None, rationale: str) -> None:
        async def grader(scenario: Scenario, trial: AgentTrial) -> Verdict:
            return verdict("stub", True, 1.0, "graded")

        grade = asyncio.run(grade_trial(SCENARIO, _trial(outcome=outcome), {"stub": grader}))

        assert [(v.grader, v.passed, v.rationale) for v in grade.verdicts] == [("stub", passed, rationale)]


MISSING = "missing tools: feature-flag-get-all"


class TestExpectedTools(SimpleTestCase):
    @parameterized.expand(
        [
            ("pass", (), (_exec("call feature-flag-get-all"),), True, "every expected tool was called"),
            ("fail_names_missing", (), (_exec("learn"),), False, MISSING),
            ("discovery_is_not_a_call", (), (_exec("info feature-flag-get-all"),), False, MISSING),
            ("no_expectation", None, (), None, "scenario lists no expected tools"),
        ]
    )
    def test_verdict(self, _name: str, expected: tuple[str, ...] | None, calls: tuple[ToolCallRecord, ...], passed: bool | None, rationale: str) -> None:  # fmt: skip
        scenario = SCENARIO if expected is not None else SCENARIO.model_copy(update={"expected_tools": ()})

        result = asyncio.run(expected_tools_grader(scenario, _trial(calls)))

        assert (result.passed, result.rationale) == (passed, rationale)


class _FakeMessages:
    def __init__(self, response: Message | anthropic.APIError) -> None:
        self.response = response
        self.sent: dict[str, object] = {}

    async def create(self, **kwargs: object) -> Message:
        self.sent = kwargs
        if isinstance(self.response, anthropic.APIError):
            raise self.response
        return self.response


def _verdict_message(*blocks: TextBlock) -> Message:
    return Message.model_construct(
        id="m", type="message", role="assistant", model="claude-sonnet-5-5", content=list(blocks),
        stop_reason="end_turn", stop_sequence=None, usage=Usage(input_tokens=1, output_tokens=1),
    )  # fmt: skip


_API_ERROR = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _verdict_use(verdict_json: dict[str, object]) -> TextBlock:
    return TextBlock(type="text", text=json.dumps(verdict_json))


def _judge(messages: _FakeMessages) -> Grader:
    return make_judge(cast(anthropic.AsyncAnthropic, SimpleNamespace(messages=messages)), "claude-sonnet-5-5")


class TestJudge(SimpleTestCase):
    @parameterized.expand(
        [
            ("pass", _verdict_message(_verdict_use({"passed": True, "rationale": "Lists the keys."})), True, 1.0, "Lists the keys."),
            ("fail", _verdict_message(_verdict_use({"passed": False, "rationale": "No keys."})), False, 0.0, "No keys."),
            ("not_json", _verdict_message(TextBlock(type="text", text="hm")), None, None, "judge returned no verdict (stop_reason end_turn)"),
            ("api_error", _API_ERROR, None, None, "judge call failed: Connection error."),
        ]
    )  # fmt: skip
    def test_verdict(self, _name: str, response: Message | anthropic.APIError, passed: bool | None, score: float | None, rationale: str) -> None:  # fmt: skip
        result = asyncio.run(_judge(_FakeMessages(response))(SCENARIO, _trial((_exec("call x"),))))

        assert result == verdict("judge", passed, score, rationale)

    def test_judge_sees_the_answer_not_tool_results_and_must_reply_in_the_verdict_schema(self) -> None:
        fake = _FakeMessages(_verdict_message(_verdict_use({"passed": True, "rationale": "ok"})))

        asyncio.run(_judge(fake)(SCENARIO, _trial((_exec("call x"),))))

        sent = fake.sent
        assert "tool_choice" not in sent
        assert sent["output_config"]["format"]["schema"]["required"] == ["passed", "rationale"]  # type: ignore[index]
        assert sent["messages"] == [
            {
                "role": "user",
                "content": "<request>\nList all our active feature flags.\n</request>\n\n"
                "<success_criteria>\nReturns the active flags by key.\n</success_criteria>\n\n"
                "<answer>\nTwo flags.\n</answer>",
            }
        ]


class _FakeJev:
    def __init__(self, outcome: SystemOneResult | Exception) -> None:
        self.outcome = outcome
        self.sent: list[tuple[JsonValue, Mapping[str, Question]]] = []

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        self.sent.append((state, questions))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _result(answer: NoulAnswer | RefusalAnswer) -> SystemOneResult:
    return SystemOneResult(model="jev-1.13.0", answers={"passed": answer}, input_tokens=10)


class TestJev(SimpleTestCase):
    @parameterized.expand(
        [
            ("high_probability_passes", _result(NoulAnswer(probability=0.9)), True, 0.9),
            ("threshold_passes", _result(NoulAnswer(probability=0.5)), True, 0.5),
            ("low_probability_fails", _result(NoulAnswer(probability=0.2)), False, 0.2),
            ("refusal_is_not_gradable", _result(RefusalAnswer()), None, None),
            ("request_failure_is_not_gradable", SystemOneRequestFailed("boom"), None, None),
        ]
    )
    def test_verdict(
        self, _name: str, outcome: SystemOneResult | Exception, passed: bool | None, score: float | None
    ) -> None:
        result = asyncio.run(make_jev(cast(SystemOneClient, _FakeJev(outcome)))(SCENARIO, _trial((_exec("call x"),))))

        assert (result.grader, result.passed, result.score) == ("jev", passed, score)

    def test_jev_receives_only_request_criteria_and_answer(self) -> None:
        fake = _FakeJev(_result(NoulAnswer(probability=0.9)))

        asyncio.run(make_jev(cast(SystemOneClient, fake))(SCENARIO, _trial((_exec("call x"),))))

        [(state, questions)] = fake.sent
        assert state == {
            "request": "List all our active feature flags.",
            "success_criteria": "Returns the active flags by key.",
            "answer": "Two flags.",
        }
        assert list(questions) == ["passed"]
        assert "SECRET" not in repr(fake.sent)


def _grade(scenario_id: str, trial: int, outcome: str, **passed: bool | None) -> TrialGrade:
    return TrialGrade(
        scenario_id=scenario_id,
        trial=trial,
        outcome=outcome,
        verdicts=tuple(verdict(name, value, None, "") for name, value in passed.items()),
    )


class TestSummary(SimpleTestCase):
    def test_pass_rates_per_scenario_and_judge_jev_disagreement(self) -> None:
        report = GradedReport(
            server_url="u", model="m", effort="low", started_at="t",
            graders=("expected_tools", "judge", "jev"),
            grades=(
                _grade("a", 1, "answered", expected_tools=True, judge=True, jev=False),
                _grade("a", 2, "answered", expected_tools=False, judge=True, jev=True),
                _grade("b", 1, "mcp_error", expected_tools=None, judge=None, jev=None),
            ),
        )  # fmt: skip

        assert format_grade_summary(report) == (
            "graded 3 trials with expected_tools, judge, jev\n"
            "  a: expected_tools 1/2, judge 2/2, jev 1/2\n"
            "  b: expected_tools 0/0, judge 0/0, jev 0/0\n"
            "judge and jev disagree on 1 of 2 trials both graded"
        )


def _report_json(scenario_id: str) -> str:
    call = {"name": "exec", "input": {"command": "call --json feature-flag-get-all {}"}, "is_error": False}
    trials = [
        {"scenario_id": scenario_id, "trial": 1, "outcome": "answered", "final_text": "Two flags.",
         "tool_calls": [{**call, "result_text": "r", "latency_ms": 1}], "turns": 2, "usage": {}, "duration_ms": 3},
        {"scenario_id": scenario_id, "trial": 2, "outcome": "turn_limit", "final_text": "",
         "tool_calls": [], "turns": 2, "usage": {}, "duration_ms": 3},
    ]  # fmt: skip
    scenario = {
        "id": "flags-list-active",
        "intent": "List all our active feature flags.",
        "success_criteria": "Returns the active flags by key.",
        "expected_tools": ["feature-flag-get-all"],
    }
    return json.dumps(
        {
            "server_url": "http://x/mcp",
            "model": "m",
            "effort": "low",
            "started_at": "t0",
            "scenarios": [scenario],
            "trials": trials,
        }
    )


class TestGradeCommand(SimpleTestCase):
    def _run(self, scenario_id: str, graders: str) -> tuple[str, str, dict[str, Any]]:
        directory = Path(tempfile.mkdtemp())
        (directory / "run.json").write_text(_report_json(scenario_id))
        out, err = StringIO(), StringIO()
        call_command(
            "grade_mcp_evals", report=directory / "run.json",
            out=directory / "graded.json", graders=graders, stdout=out, stderr=err,
        )  # fmt: skip
        return out.getvalue(), err.getvalue(), json.loads((directory / "graded.json").read_text())

    def test_grades_a_saved_report_and_writes_json(self) -> None:
        summary, _, written = self._run("flags-list-active", "expected_tools")

        assert summary.splitlines()[:2] == [
            "graded 2 trials with expected_tools",
            "  flags-list-active: expected_tools 1/2",
        ]
        assert [(g["trial"], g["outcome"], [v["passed"] for v in g["verdicts"]]) for g in written["grades"]] == [
            (1, "answered", [True]),
            (2, "turn_limit", [False]),
        ]

    @parameterized.expand(
        [
            ("unknown_scenario", "gone", "expected_tools", "trials for scenarios it does not record: gone"),
            ("unknown_grader", "flags-list-active", "expected_tools,bogus", "unknown graders: bogus"),
        ]
    )
    def test_bad_input_fails_before_grading(self, _name: str, scenario_id: str, graders: str, message: str) -> None:
        with self.assertRaisesMessage(CommandError, message):
            self._run(scenario_id, graders)

    @override_settings(ANTHROPIC_API_KEY=None)
    def test_a_grader_without_credentials_is_skipped_with_an_error(self) -> None:
        _, err, written = self._run("flags-list-active", "expected_tools,judge")

        assert err.strip() == "skipping grader judge: judge needs ANTHROPIC_API_KEY"
        assert written["graders"] == ["expected_tools"]
