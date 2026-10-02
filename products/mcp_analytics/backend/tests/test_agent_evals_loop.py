import asyncio
from collections.abc import Awaitable, Callable

from django.test import SimpleTestCase

import httpx
import anthropic
from anthropic.types import Message, MessageParam, TextBlock, ToolUseBlock, Usage
from parameterized import parameterized

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial, ToolOutcome, TrialDeps, run_trial
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

SCENARIO = Scenario(
    id="flags-list-active",
    intent="List all our active feature flags.",
    success_criteria="Returns the active flags by key.",
)


def _message(stop_reason: str, content: list[TextBlock | ToolUseBlock]) -> Message:
    return Message.model_construct(
        id="msg",
        type="message",
        role="assistant",
        model="claude-opus-5-5",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=5, cache_read_input_tokens=3),
    )


def _text(value: str) -> TextBlock:
    return TextBlock(type="text", text=value)


def _tool_use(use_id: str, name: str) -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=use_id, name=name, input={})


def _api_error() -> anthropic.APIError:
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


class _Scripted:
    def __init__(self, responses: list[Message | anthropic.APIError]) -> None:
        self.responses = responses
        self.sent: list[list[MessageParam]] = []

    async def create_message(self, messages: list[MessageParam]) -> Message:
        self.sent.append(list(messages))
        response = self.responses[min(len(self.sent), len(self.responses)) - 1]
        if isinstance(response, anthropic.APIError):
            raise response
        return response


def _run(script: _Scripted, call_tool: Callable[[str, object], Awaitable[ToolOutcome]], max_turns: int) -> AgentTrial:
    deps = TrialDeps(create_message=script.create_message, call_tool=call_tool, now_ms=lambda: 0)
    return asyncio.run(run_trial(SCENARIO, 1, max_turns, deps))


async def _ok_tool(name: str, tool_input: object) -> ToolOutcome:
    return ToolOutcome(text="[]", is_error=False)


class TestAgentTrialLoop(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_final_reply_after_a_tool_call_is_answered",
                [
                    _message("tool_use", [_tool_use("t1", "feature-flag-get-all")]),
                    _message("end_turn", [_text("Two flags.")]),
                ],
                "answered",
                2,
                "Two flags.",
            ),
            (
                "a_model_that_never_stops_calling_tools_hits_the_turn_limit",
                [_message("tool_use", [_text("Checking."), _tool_use("t1", "feature-flag-get-all")])],
                "turn_limit",
                3,
                "Checking.",
            ),
            ("an_api_failure_is_a_model_error_not_an_answer", [_api_error()], "model_error", 0, ""),
            ("a_refusal_is_recorded_as_refused", [_message("refusal", [])], "refused", 1, ""),
            (
                "a_cut_off_response_is_truncated",
                [_message("max_tokens", [_text("Partial")])],
                "truncated",
                1,
                "Partial",
            ),
            (
                "a_stop_reason_the_loop_cannot_continue_from_is_a_model_error",
                [_message("pause_turn", [_text("Paused")])],
                "model_error",
                1,
                "Paused",
            ),
        ]
    )
    def test_trial_outcome(
        self,
        _name: str,
        responses: list[Message | anthropic.APIError],
        outcome: str,
        turns: int,
        final_text: str,
    ) -> None:
        trial = _run(_Scripted(responses), _ok_tool, max_turns=3)

        assert (trial.outcome, trial.turns, trial.final_text) == (outcome, turns, final_text)
        assert (trial.usage.input_tokens, trial.usage.cache_read_input_tokens) == (10 * turns, 3 * turns)

    def test_parallel_tool_results_return_in_one_message_and_a_thrown_call_becomes_an_error(self) -> None:
        async def call_tool(name: str, tool_input: object) -> ToolOutcome:
            if name == "execute-sql":
                raise ConnectionError("socket hang up")
            return ToolOutcome(text='[{"key":"beta"}]', is_error=False)

        script = _Scripted(
            [
                _message("tool_use", [_tool_use("t1", "feature-flag-get-all"), _tool_use("t2", "execute-sql")]),
                _message("end_turn", [_text("Done.")]),
            ]
        )

        trial = _run(script, call_tool, max_turns=5)

        assert trial.outcome == "answered"
        assert [(call.name, call.is_error, call.result_text) for call in trial.tool_calls] == [
            ("feature-flag-get-all", False, '[{"key":"beta"}]'),
            ("execute-sql", True, "socket hang up"),
        ]
        assert script.sent[1][-1] == {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": '[{"key":"beta"}]', "is_error": False},
                {"type": "tool_result", "tool_use_id": "t2", "content": "socket hang up", "is_error": True},
            ],
        }
