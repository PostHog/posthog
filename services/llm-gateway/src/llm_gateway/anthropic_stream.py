from __future__ import annotations

import codecs
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from llm_gateway.metrics.prometheus import ANTHROPIC_BRIDGE_INVALID_STREAM

_DELTA_BLOCK_TYPES = {
    "compaction_delta": "compaction",
    "input_json_delta": "tool_use",
    "signature_delta": "thinking",
    "text_delta": "text",
    "thinking_delta": "thinking",
}
_SSE_FRAME_SEPARATOR = re.compile(r"\r?\n\r?\n")


class _SSEPayloadDecoder:
    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._buffer = ""

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        try:
            self._buffer += self._decoder.decode(chunk)
        except UnicodeDecodeError:
            self._decoder.reset()
            self._buffer = ""
            return []

        frames: list[str] = []
        while match := _SSE_FRAME_SEPARATOR.search(self._buffer):
            frames.append(self._buffer[: match.start()])
            self._buffer = self._buffer[match.end() :]
        return self._parse_frames(frames)

    def finish(self) -> list[dict[str, Any]]:
        try:
            self._buffer += self._decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            self._buffer = ""
            return []

        final_frame = self._buffer
        self._buffer = ""
        return self._parse_frames([final_frame]) if final_frame.strip() else []

    @staticmethod
    def _parse_frames(frames: list[str]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for frame in frames:
            data_lines = []
            for line in frame.splitlines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:")
                data_lines.append(data.removeprefix(" "))
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads


async def observe_anthropic_stream(stream: AsyncIterator[Any], backend: str) -> AsyncIterator[Any]:
    active_blocks: dict[int, str] = {}
    recorded_violations: set[tuple[int, str]] = set()
    sse_decoder = _SSEPayloadDecoder()

    async for chunk in stream:
        for payload in _payloads_from_chunk(chunk, sse_decoder):
            _observe_payload(payload, backend, active_blocks, recorded_violations)
        yield chunk

    for payload in sse_decoder.finish():
        _observe_payload(payload, backend, active_blocks, recorded_violations)
    for index in active_blocks:
        _record_violation(backend, index, "unclosed_block", recorded_violations)


def _payloads_from_chunk(chunk: Any, sse_decoder: _SSEPayloadDecoder) -> list[dict[str, Any]]:
    if isinstance(chunk, dict):
        return [chunk]
    if hasattr(chunk, "model_dump"):
        payload = chunk.model_dump()
        return [payload] if isinstance(payload, dict) else []
    if isinstance(chunk, bytes):
        return sse_decoder.feed(chunk)
    return []


def _observe_payload(
    payload: dict[str, Any],
    backend: str,
    active_blocks: dict[int, str],
    recorded_violations: set[tuple[int, str]],
) -> None:
    event_type = payload.get("type")
    index = payload.get("index")
    if not isinstance(index, int):
        return

    if event_type == "content_block_start":
        if index in active_blocks:
            _record_violation(backend, index, "duplicate_start", recorded_violations)
            return
        content_block = payload.get("content_block")
        block_type = content_block.get("type") if isinstance(content_block, dict) else None
        if isinstance(block_type, str):
            active_blocks[index] = block_type
        return

    if event_type == "content_block_stop":
        if active_blocks.pop(index, None) is None:
            _record_violation(backend, index, "stop_without_start", recorded_violations)
        return

    if event_type != "content_block_delta":
        return

    block_type = active_blocks.get(index)
    if block_type is None:
        _record_violation(backend, index, "delta_without_start", recorded_violations)
        return

    delta = payload.get("delta")
    delta_type = delta.get("type") if isinstance(delta, dict) else None
    expected_block_type = _DELTA_BLOCK_TYPES.get(delta_type) if isinstance(delta_type, str) else None
    if expected_block_type is not None and block_type != expected_block_type:
        _record_violation(backend, index, "delta_type_mismatch", recorded_violations)


def _record_violation(
    backend: str,
    index: int,
    violation: str,
    recorded_violations: set[tuple[int, str]],
) -> None:
    violation_key = (index, violation)
    if violation_key in recorded_violations:
        return
    recorded_violations.add(violation_key)
    ANTHROPIC_BRIDGE_INVALID_STREAM.labels(backend=backend, violation=violation).inc()
