from __future__ import annotations

import re
import json
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str
    contains: str


class ResponseStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["claude", "codex"]
    model: str
    fixture: Literal["text", "insight-update", "tool-search"]
    user_message: str
    tool_result: ToolResult | None = None
    substitutions: dict[str, str]


def object_value(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def substitute(value: JsonValue, substitutions: dict[str, str]) -> JsonValue:
    if isinstance(value, str):
        return re.sub(r"\{\{([a-z_]+)\}\}", lambda match: substitutions[match[1]], value)
    if isinstance(value, list):
        return [substitute(item, substitutions) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, substitutions) for key, item in value.items()}
    return value


def fixture_events(step: ResponseStep) -> list[dict[str, JsonValue]]:
    allowed = {"message_id", "tool_call_id", "resource_id", "text", "model", "arguments", "tool_name", "tool_namespace"}
    if set(step.substitutions) - allowed:
        raise ValueError("Unknown fixture substitution")
    fixtures = Path(__file__).resolve().parents[5] / "products/posthog_ai/frontend/e2e/fixtures"
    path = fixtures / step.provider / f"{step.fixture}.ndjson"
    return [object_value(substitute(json.loads(line), step.substitutions)) for line in path.read_text().splitlines()]


def sse_frames(events: list[dict[str, JsonValue]]) -> bytes:
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()


def request_items(provider: str, body: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    items = body.get("messages" if provider == "claude" else "input")
    if not isinstance(items, list):
        raise ValueError("Model request has no conversation")
    return [object_value(item) for item in items]


def content_blocks(item: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    content = item.get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def validate_step(step: ResponseStep, provider: str, body: dict[str, JsonValue]) -> None:
    if provider != step.provider or body.get("model") != step.model or body.get("stream") is not True:
        raise ValueError(f"Expected streaming {step.provider}/{step.model}")
    items = request_items(provider, body)
    users = [item for item in items if item.get("role") == "user"]
    # Anthropic represents tool results as a user turn; they do not advance the human conversation.
    users = [item for item in users if not any(block.get("type") == "tool_result" for block in content_blocks(item))]
    if not users or step.user_message not in json.dumps(users[-1], ensure_ascii=False):
        raise ValueError("Unexpected human conversation step")
    results = [
        block
        for item in items
        for block in ([item] if provider == "codex" else content_blocks(item))
        if isinstance(block, dict)
        and block.get("type") in {"tool_result", "function_call_output", "tool_search_output"}
    ]
    expected = step.tool_result
    if expected:
        matching = [
            result for result in results if result.get("tool_use_id", result.get("call_id")) == expected.call_id
        ]
        if (
            len(matching) != 1
            or matching[0].get("is_error")
            or expected.contains not in json.dumps(matching[0], ensure_ascii=False)
        ):
            raise ValueError("Expected successful real tool result is missing")
        if results[-1] != matching[0]:
            raise ValueError("Unexpected tool result after the expected result")
    elif results:
        raise ValueError("Unexpected tool result")
    if step.fixture == "insight-update":
        tools = body.get("tools")
        offered = list(tools) if isinstance(tools, list) else []
        for result in results:
            discovered = result.get("tools")
            if result.get("type") == "tool_search_output" and isinstance(discovered, list):
                offered.extend(discovered)
        namespace = step.substitutions.get("tool_namespace")
        if namespace:
            namespaced: list[JsonValue] = []
            for tool in offered:
                if isinstance(tool, dict) and tool.get("type") == "namespace" and tool.get("name") == namespace:
                    nested = tool.get("tools")
                    if isinstance(nested, list):
                        namespaced.extend(nested)
            offered = namespaced
        if not any(isinstance(tool, dict) and tool.get("name") == step.substitutions["tool_name"] for tool in offered):
            raise ValueError("Fixture tool is not offered by the real agent")
    if step.fixture == "tool-search":
        tools = body.get("tools")
        if not isinstance(tools, list) or not any(
            isinstance(tool, dict) and tool.get("type") == "tool_search" for tool in tools
        ):
            raise ValueError("Agent does not offer tool search")


class Replay:
    def __init__(self, steps: list[ResponseStep]) -> None:
        if not steps:
            raise ValueError("Declare at least one model response")
        self.steps = steps
        self.cursor = 0
        self.consumed: list[dict[str, JsonValue]] = []
        self.errors: list[str] = []
        self.lock = threading.Lock()
        for step in steps:
            fixture_events(step)

    def respond(self, provider: str, body: dict[str, JsonValue]) -> bytes:
        with self.lock:
            try:
                if self.cursor == len(self.steps):
                    raise ValueError("Unexpected request after final response")
                step = self.steps[self.cursor]
                validate_step(step, provider, body)
                transcript = json.dumps(request_items(provider, body), ensure_ascii=False)
                expected_messages = list(dict.fromkeys(prior.user_message for prior in self.steps[: self.cursor + 1]))
                positions = [transcript.find(message) for message in expected_messages]
                if any(position < 0 for position in positions) or positions != sorted(positions):
                    raise ValueError("Conversation history does not match the declared response sequence")
                frames = sse_frames(fixture_events(step))
                self.consumed.append(
                    {"step": self.cursor, "provider": provider, "model": step.model, "fixture": step.fixture}
                )
                self.cursor += 1
                return frames
            except Exception as error:
                self.errors.append(str(error))
                raise

    def verify(self) -> None:
        if self.errors or self.cursor != len(self.steps):
            raise AssertionError(f"Replay consumed {self.cursor}/{len(self.steps)} responses; errors: {self.errors}")
