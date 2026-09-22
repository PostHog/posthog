from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolCall, ToolMessage
from pydantic import BaseModel, ValidationError

from posthog.sync import database_sync_to_async

from products.exports.backend.temporal.subscriptions.ai_subscription.context_tools import (
    CONTEXT_TOOL_NAMES,
    MAX_TOOL_ROUNDS,
    ContextToolRuntime,
)

from ee.hogai.llm import MaxChatOpenAI

_TOOL_BUDGET_EXHAUSTED_MESSAGE = "Tool budget exhausted. Answer now without further tool calls."


async def _dispatch_tool_call(
    tool_call: ToolCall,
    *,
    runtime: ContextToolRuntime,
    schemas_by_name: dict[str, type[BaseModel]],
) -> ToolMessage:
    name = tool_call["name"]
    # LangChain types ToolCall.id as Optional[str], but ToolMessage.tool_call_id requires str;
    # a real tool-calling model always sets it, so the fallback only satisfies the type checker.
    tool_call_id = tool_call["id"] or ""
    schema = schemas_by_name.get(name)
    if schema is None:
        return ToolMessage(content=f"unknown tool: {name}", tool_call_id=tool_call_id)
    try:
        validated_args = schema(**tool_call["args"]).model_dump()
    except ValidationError as exc:
        return ToolMessage(content=f"invalid arguments for {name}: {exc}", tool_call_id=tool_call_id)
    result = await runtime.dispatch(name, validated_args)
    return ToolMessage(content=result, tool_call_id=tool_call_id)


async def run_tool_loop(
    *,
    llm: MaxChatOpenAI,
    messages: list[BaseMessage],
    runtime: ContextToolRuntime,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> list[BaseMessage]:
    transcript: list[BaseMessage] = list(messages)
    schemas_by_name = dict(zip(CONTEXT_TOOL_NAMES, runtime.tool_schemas()))
    bound = llm.bind_tools(runtime.tool_schemas())

    for _round in range(max_rounds):
        response = await database_sync_to_async(bound.invoke, thread_sensitive=False)(transcript)
        transcript.append(response)
        tool_calls = response.tool_calls if isinstance(response, AIMessage) else []
        if not tool_calls:
            return transcript
        for tool_call in tool_calls:
            transcript.append(await _dispatch_tool_call(tool_call, runtime=runtime, schemas_by_name=schemas_by_name))

    transcript.append(HumanMessage(_TOOL_BUDGET_EXHAUSTED_MESSAGE))
    final_response = await database_sync_to_async(llm.invoke, thread_sensitive=False)(transcript)
    transcript.append(final_response)
    return transcript
