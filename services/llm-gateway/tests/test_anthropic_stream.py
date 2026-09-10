from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from litellm.llms.anthropic.experimental_pass_through.adapters.streaming_iterator import AnthropicStreamWrapper
from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices

from llm_gateway.anthropic_stream import observe_anthropic_stream
from llm_gateway.metrics.prometheus import ANTHROPIC_BRIDGE_INVALID_STREAM


def _chunk(
    *,
    reasoning_content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
) -> ModelResponseStream:
    return ModelResponseStream(
        choices=[
            StreamingChoices(
                index=0,
                finish_reason=finish_reason,
                delta=Delta(
                    role="assistant",
                    reasoning_content=reasoning_content,
                    tool_calls=tool_calls,
                ),
            )
        ]
    )


def _glm_stream(label: str) -> Iterator[ModelResponseStream]:
    return iter(
        [
            _chunk(reasoning_content=f"plan-{label}"),
            _chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": f"call-{label}",
                        "type": "function",
                        "function": {"name": "shell", "arguments": ""},
                    }
                ]
            ),
            _chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": None,
                        "type": "function",
                        "function": {"name": None, "arguments": "{}"},
                    }
                ]
            ),
            _chunk(finish_reason="tool_calls"),
        ]
    )


def _assert_valid_event_order(events: list[dict[str, Any]]) -> None:
    active_blocks: dict[int, str] = {}
    delta_block_types = {
        "input_json_delta": "tool_use",
        "signature_delta": "thinking",
        "text_delta": "text",
        "thinking_delta": "thinking",
    }

    for event in events:
        event_type = event.get("type")
        index = event.get("index")
        if event_type == "content_block_start":
            assert isinstance(index, int)
            assert index not in active_blocks
            active_blocks[index] = event["content_block"]["type"]
        elif event_type == "content_block_delta":
            assert isinstance(index, int)
            assert index in active_blocks
            expected_block_type = delta_block_types.get(event["delta"]["type"])
            if expected_block_type is not None:
                assert active_blocks[index] == expected_block_type
        elif event_type == "content_block_stop":
            assert isinstance(index, int)
            assert index in active_blocks
            active_blocks.pop(index)


def test_litellm_anthropic_streams_do_not_share_event_queues() -> None:
    wrappers = [
        AnthropicStreamWrapper(_glm_stream("a"), model="glm-a"),
        AnthropicStreamWrapper(_glm_stream("b"), model="glm-b"),
    ]
    outputs: list[list[dict[str, Any]]] = [[], []]
    completed = [False, False]

    while not all(completed):
        for index, wrapper in enumerate(wrappers):
            if completed[index]:
                continue
            try:
                event = next(wrapper)
            except (StopIteration, StopAsyncIteration):
                completed[index] = True
                continue
            assert isinstance(event, dict)
            outputs[index].append(event)

    for output in outputs:
        _assert_valid_event_order(output)
    assert "call-b" not in json.dumps(outputs[0])
    assert "call-a" not in json.dumps(outputs[1])


def test_litellm_anthropic_stream_uses_matching_thinking_block() -> None:
    events = list(AnthropicStreamWrapper(_glm_stream("a"), model="glm-a"))
    dict_events = [event for event in events if isinstance(event, dict)]

    _assert_valid_event_order(dict_events)


@pytest.mark.parametrize("serialize", [False, True], ids=["structured", "sse_bytes"])
async def test_observer_records_invalid_stream_without_modifying_it(serialize: bool) -> None:
    event = {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{}"}}
    chunks = [f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() if serialize else event] * 2

    async def stream() -> AsyncIterator[Any]:
        for chunk in chunks:
            yield chunk

    labels = ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend="test", violation="delta_without_start")
    initial_value = labels._value.get()

    observed = [chunk async for chunk in observe_anthropic_stream(stream(), "test")]

    assert observed == chunks
    assert labels._value.get() == initial_value + 1


async def test_observer_accepts_compaction_delta_for_compaction_block() -> None:
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "compaction", "content": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "compaction_delta", "content": "summary"}},
        {"type": "content_block_stop", "index": 0},
    ]

    async def stream() -> AsyncIterator[dict[str, Any]]:
        for event in events:
            yield event

    labels = ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend="test", violation="delta_type_mismatch")
    initial_value = labels._value.get()

    observed = [event async for event in observe_anthropic_stream(stream(), "test")]

    assert observed == events
    assert labels._value.get() == initial_value


async def test_observer_handles_fragmented_and_coalesced_sse_frames() -> None:
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_stop", "index": 0},
    ]
    encoded = b"".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() for event in events)
    chunks = [encoded[:23], encoded[23:]]

    async def stream() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    delta_labels = ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend="test", violation="delta_without_start")
    unclosed_labels = ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend="test", violation="unclosed_block")
    initial_delta_value = delta_labels._value.get()
    initial_unclosed_value = unclosed_labels._value.get()

    observed = [chunk async for chunk in observe_anthropic_stream(stream(), "test")]

    assert observed == chunks
    assert delta_labels._value.get() == initial_delta_value
    assert unclosed_labels._value.get() == initial_unclosed_value


async def test_observer_records_unclosed_block_at_normal_eof() -> None:
    events = [{"type": "content_block_start", "index": 3, "content_block": {"type": "text", "text": ""}}]

    async def stream() -> AsyncIterator[dict[str, Any]]:
        for event in events:
            yield event

    labels = ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend="test", violation="unclosed_block")
    initial_value = labels._value.get()

    observed = [event async for event in observe_anthropic_stream(stream(), "test")]

    assert observed == events
    assert labels._value.get() == initial_value + 1


async def test_duplicate_start_preserves_original_block_type() -> None:
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "name": "shell"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_stop", "index": 0},
    ]

    async def stream() -> AsyncIterator[dict[str, Any]]:
        for event in events:
            yield event

    duplicate_labels = ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend="test", violation="duplicate_start")
    mismatch_labels = ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend="test", violation="delta_type_mismatch")
    initial_duplicate_value = duplicate_labels._value.get()
    initial_mismatch_value = mismatch_labels._value.get()

    observed = [event async for event in observe_anthropic_stream(stream(), "test")]

    assert observed == events
    assert duplicate_labels._value.get() == initial_duplicate_value + 1
    assert mismatch_labels._value.get() == initial_mismatch_value
