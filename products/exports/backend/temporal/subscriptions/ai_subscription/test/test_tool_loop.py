from typing import Any, cast

from unittest.mock import AsyncMock, MagicMock

from django.test import SimpleTestCase

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from parameterized import parameterized
from pydantic import BaseModel

from products.exports.backend.temporal.subscriptions.ai_subscription.context_tools import (
    ContextToolRuntime,
    FetchDashboardArgs,
    FetchInsightArgs,
    ListSelectedContextsArgs,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.tool_loop import run_tool_loop

from ee.hogai.llm import MaxChatOpenAI


class _StubLLM:
    def __init__(self, invoke: MagicMock) -> None:
        self.invoke = invoke

    def bind_tools(self, schemas: list[type[BaseModel]]) -> "_StubLLM":
        return self


class _StubRuntime:
    def __init__(self, dispatch_result: str = "dispatch result") -> None:
        self.dispatch = AsyncMock(return_value=dispatch_result)

    def tool_schemas(self) -> list[type[BaseModel]]:
        return [ListSelectedContextsArgs, FetchInsightArgs, FetchDashboardArgs]


def _tool_call_message(*, name: str = "fetch_insight", args: dict[str, Any], call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


async def _run(llm: _StubLLM, runtime: _StubRuntime, *, max_rounds: int | None = None) -> list[Any]:
    kwargs: dict[str, Any] = {} if max_rounds is None else {"max_rounds": max_rounds}
    return await run_tool_loop(
        llm=cast(MaxChatOpenAI, llm),
        messages=[HumanMessage("hi")],
        runtime=cast(ContextToolRuntime, runtime),
        **kwargs,
    )


class TestRunToolLoop(SimpleTestCase):
    async def test_executes_tool_calls_and_returns_on_plain_answer(self) -> None:
        final_message = AIMessage(content="done")
        llm = _StubLLM(MagicMock(side_effect=[_tool_call_message(args={"insight_id": 1}), final_message]))
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime)

        runtime.dispatch.assert_called_once_with("fetch_insight", {"insight_id": 1})
        assert transcript[-1] is final_message
        tool_messages = [message for message in transcript if isinstance(message, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "dispatch result"
        assert tool_messages[0].tool_call_id == "c1"

    async def test_round_cap_forces_final_unbound_answer(self) -> None:
        llm = _StubLLM(MagicMock(side_effect=lambda *_args, **_kwargs: _tool_call_message(args={"insight_id": 1})))
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime, max_rounds=2)

        assert runtime.dispatch.call_count == 2
        assert llm.invoke.call_count == 3
        exhaustion_messages = [
            message
            for message in transcript
            if isinstance(message, HumanMessage) and "tool budget exhausted" in str(message.content).lower()
        ]
        assert len(exhaustion_messages) == 1
        assert isinstance(transcript[-1], AIMessage)
        assert transcript[-2] is exhaustion_messages[0]

    @parameterized.expand(
        [
            ("unknown_tool_name", "drop_tables", {}, "unknown tool"),
            ("malformed_known_tool_args", "fetch_insight", {}, "insight_id"),
        ]
    )
    async def test_unknown_tool_yields_error_tool_message(
        self, _name: str, tool_name: str, args: dict[str, Any], expected_fragment: str
    ) -> None:
        final_message = AIMessage(content="done")
        llm = _StubLLM(MagicMock(side_effect=[_tool_call_message(name=tool_name, args=args), final_message]))
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime)

        runtime.dispatch.assert_not_called()
        tool_messages = [message for message in transcript if isinstance(message, ToolMessage)]
        assert len(tool_messages) == 1
        assert expected_fragment in str(tool_messages[0].content).lower()
