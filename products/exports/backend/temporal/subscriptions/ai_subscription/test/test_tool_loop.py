from typing import Any, cast

from unittest.mock import AsyncMock, MagicMock

from django.test import SimpleTestCase

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
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


def _tool_name(schema: type[BaseModel]) -> str:
    return str(convert_to_openai_tool(schema)["function"]["name"])


class _BoundLLM:
    def __init__(self, invoke: MagicMock) -> None:
        self.invoke = invoke


class _StubLLM:
    def __init__(self, bound_invoke: MagicMock, invoke: MagicMock | None = None) -> None:
        self.bound_invoke = bound_invoke
        self.invoke = invoke if invoke is not None else MagicMock()

    def bind_tools(self, schemas: list[type[BaseModel]]) -> _BoundLLM:
        return _BoundLLM(self.bound_invoke)


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
        # The tool name is derived the same way a real model's response carries it (via
        # convert_to_openai_tool on the schema), not hard-coded, so this fails if the dispatch
        # lookup and bind_tools() ever name a tool differently again.
        final_message = AIMessage(content="done")
        tool_name = _tool_name(FetchInsightArgs)
        llm = _StubLLM(
            bound_invoke=MagicMock(
                side_effect=[_tool_call_message(name=tool_name, args={"insight_id": 1}), final_message]
            )
        )
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime)

        runtime.dispatch.assert_called_once_with("fetch_insight", {"insight_id": 1})
        llm.invoke.assert_not_called()
        assert transcript[-1] is final_message
        tool_messages = [message for message in transcript if isinstance(message, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "dispatch result"
        assert tool_messages[0].tool_call_id == "c1"

    async def test_round_cap_forces_final_unbound_answer(self) -> None:
        tool_name = _tool_name(FetchInsightArgs)
        llm = _StubLLM(
            bound_invoke=MagicMock(
                side_effect=lambda *_a, **_kw: _tool_call_message(name=tool_name, args={"insight_id": 1})
            ),
            invoke=MagicMock(return_value=AIMessage(content="final answer")),
        )
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime, max_rounds=2)

        assert runtime.dispatch.call_count == 2
        assert llm.bound_invoke.call_count == 2
        llm.invoke.assert_called_once()
        exhaustion_messages = [
            message
            for message in transcript
            if isinstance(message, HumanMessage) and "tool budget exhausted" in str(message.content).lower()
        ]
        assert len(exhaustion_messages) == 1
        assert transcript[-2] is exhaustion_messages[0]
        assert transcript[-1].content == "final answer"

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
        llm = _StubLLM(
            bound_invoke=MagicMock(side_effect=[_tool_call_message(name=tool_name, args=args), final_message])
        )
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime)

        runtime.dispatch.assert_not_called()
        tool_messages = [message for message in transcript if isinstance(message, ToolMessage)]
        assert len(tool_messages) == 1
        assert expected_fragment in str(tool_messages[0].content).lower()

    async def test_invalid_tool_call_yields_error_tool_message_and_continues_loop(self) -> None:
        invalid_message = AIMessage(
            content="",
            invalid_tool_calls=[{"name": "fetch_insight", "args": "{not json", "id": "c1", "error": "malformed JSON"}],
        )
        final_message = AIMessage(content="done")
        llm = _StubLLM(bound_invoke=MagicMock(side_effect=[invalid_message, final_message]))
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime)

        runtime.dispatch.assert_not_called()
        assert llm.bound_invoke.call_count == 2
        llm.invoke.assert_not_called()
        tool_messages = [message for message in transcript if isinstance(message, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "c1"
        assert "malformed json" in str(tool_messages[0].content).lower()
        assert transcript[-1] is final_message

    async def test_mixed_valid_and_invalid_tool_calls_are_all_answered(self) -> None:
        tool_name = _tool_name(FetchInsightArgs)
        mixed_message = AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": {"insight_id": 1}, "id": "valid-1"}],
            invalid_tool_calls=[
                {"name": "fetch_insight", "args": "{not json", "id": "invalid-1", "error": "malformed JSON"}
            ],
        )
        final_message = AIMessage(content="done")
        llm = _StubLLM(bound_invoke=MagicMock(side_effect=[mixed_message, final_message]))
        runtime = _StubRuntime()

        transcript = await _run(llm, runtime)

        runtime.dispatch.assert_called_once_with("fetch_insight", {"insight_id": 1})
        tool_message_ids = {message.tool_call_id for message in transcript if isinstance(message, ToolMessage)}
        assert tool_message_ids == {"valid-1", "invalid-1"}
