from typing import Any

import pytest

from products.replay_vision.backend.temporal.conversation import run_tool_loop


class _FC:
    def __init__(self, name: str, args: dict[str, Any]) -> None:
        self.name = name
        self.args = args


class _Part:
    def __init__(self, function_call: Any = None) -> None:
        self.function_call = function_call


class _Resp:
    """Minimal stand-in for a genai response: `.candidates[0].content.parts` and `.text`."""

    def __init__(self, parts: list[_Part], text: str = "") -> None:
        content = type("C", (), {"parts": parts})()
        self.candidates = [type("Cand", (), {"content": content})()]
        self.text = text


def _sequence_generator(responses: list[_Resp]) -> tuple[Any, list[list[Any]]]:
    """A fake `generate` returning canned responses in order; records the convo it saw each call."""
    seen: list[list[Any]] = []
    it = iter(responses)

    async def generate(convo: list[Any]) -> _Resp:
        seen.append(list(convo))
        return next(it)

    return generate, seen


@pytest.mark.asyncio
async def test_returns_immediately_when_no_tool_call() -> None:
    final = _Resp([_Part()], text='{"verdict":"yes"}')
    generate, seen = _sequence_generator([final])
    result = await run_tool_loop(generate=generate, convo=["start"], dispatch=lambda c: {}, max_tool_iterations=6)
    assert result is final
    assert len(seen) == 1  # one generate, no tool round-trips


@pytest.mark.asyncio
async def test_runs_tool_then_returns_final() -> None:
    call = _Resp([_Part(function_call=_FC("get_events_around", {"rec_t": 30}))])
    final = _Resp([_Part()], text='{"verdict":"yes"}')
    generate, seen = _sequence_generator([call, final])
    dispatched: list[Any] = []

    def dispatch(fc: Any) -> dict[str, Any]:
        dispatched.append(fc)
        return {"events": [{"rec_t": 31, "event": "$rageclick"}]}

    result = await run_tool_loop(generate=generate, convo=["start"], dispatch=dispatch)
    assert result is final
    assert [fc.args for fc in dispatched] == [{"rec_t": 30}]
    # The 2nd generate saw the original content + the model's tool-call content + the function_response.
    assert len(seen[1]) == 3
    assert getattr(seen[1][-1], "function_response", None) is not None


@pytest.mark.asyncio
async def test_stops_at_the_tool_budget() -> None:
    always_calls = [_Resp([_Part(function_call=_FC("get_events_around", {"rec_t": i}))]) for i in range(10)]
    generate, seen = _sequence_generator(always_calls)
    result = await run_tool_loop(
        generate=generate, convo=["start"], dispatch=lambda c: {"events": []}, max_tool_iterations=2
    )
    # initial generate + 2 iterations = 3 calls, then we stop and return the last response.
    assert len(seen) == 3
    assert result is always_calls[2]
