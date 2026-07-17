"""Drive a tool-using Gemini turn: run the tools the model asks for, feed results back, return the final response."""

from collections.abc import Awaitable, Callable
from typing import Any

from google.genai import types

# Tool round-trips allowed before we stop and hand back whatever the model last produced.
DEFAULT_MAX_TOOL_ITERATIONS = 6


def function_calls(response: Any) -> list[Any]:
    """The `function_call` parts the model emitted on this response, if any."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return []
    parts = getattr(candidates[0].content, "parts", None) or []
    return [part.function_call for part in parts if getattr(part, "function_call", None)]


async def run_tool_loop(
    *,
    generate: Callable[[list[Any]], Awaitable[Any]],
    convo: list[Any],
    dispatch: Callable[[Any], dict[str, Any]],
    max_tool_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
) -> Any:
    """Run `generate` until the model answers instead of calling a tool.

    `generate(convo)` performs one `generate_content` (model + config bound by the caller). For each
    `function_call` the model emits, we run `dispatch(call)` and feed the JSON result back — appending the
    model's full content first so Gemini 3 thought signatures survive the round-trip. `convo` is mutated in
    place: every tool round-trip is appended as it happens, so a multi-turn caller keeps the full history.
    The final answer's content is NOT appended — the caller validates it, then appends it (on success) to
    continue the conversation, or appends a correction (on failure) to re-prompt. Returns the final response;
    if the tool budget runs out we return the last response and let the caller validate it.
    """
    response = await generate(convo)
    for _ in range(max_tool_iterations):
        calls = function_calls(response)
        if not calls:
            return response
        convo.append(response.candidates[0].content)  # carries thought signatures
        for call in calls:
            convo.append(types.Part(function_response=types.FunctionResponse(name=call.name, response=dispatch(call))))
        response = await generate(convo)
    return response
