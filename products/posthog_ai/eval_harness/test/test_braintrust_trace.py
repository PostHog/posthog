from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from products.posthog_ai.eval_harness.acp_log import GenerationDescriptor, ParsedLog, ToolDescriptor
from products.posthog_ai.eval_harness.base import log_agent_spans


class _Span:
    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    def log(self, **event: Any) -> None:
        self.logs.append(event)


class _Hooks:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.spans: list[tuple[str, str, float | None, float | None, _Span]] = []

    @contextmanager
    def start_span(self, name: str, kind: str, start_time: float | None = None, end_time: float | None = None):
        span = _Span()
        self.spans.append((name, kind, start_time, end_time, span))
        yield span


def test_agent_trace_uses_model_turns_and_tool_calls() -> None:
    parsed = ParsedLog(
        model="claude-haiku-4-5",
        generations=[
            GenerationDescriptor(
                input_messages=[{"role": "user", "content": "find it"}],
                output_content=[
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "search",
                        "input": {"query": "signals"},
                    }
                ],
                token_usage={"inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
                start_ts="2026-08-21T10:00:00Z",
                end_ts="2026-08-21T10:00:02Z",
            ),
            GenerationDescriptor(
                input_messages=[
                    {"role": "user", "content": "find it"},
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool-1",
                                "name": "search",
                                "input": {"query": "signals"},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "found"}],
                    },
                ],
                output_content=[{"type": "text", "text": "done"}],
                start_ts="2026-08-21T10:00:04Z",
                end_ts="2026-08-21T10:00:06Z",
            ),
        ],
        tools=[
            ToolDescriptor(
                tool_call_id="tool-1",
                name="search",
                input={"query": "signals"},
                output="found",
                start_ts="2026-08-21T10:00:02Z",
                end_ts="2026-08-21T10:00:04Z",
            )
        ],
    )
    hooks = _Hooks()

    log_agent_spans(hooks, parsed)  # type: ignore[arg-type]

    assert [(name, kind) for name, kind, _, _, _ in hooks.spans] == [
        ("model turn 1", "llm"),
        ("search", "tool"),
        ("model turn 2", "llm"),
    ]
    assert hooks.spans[0][2:4] == (1787306400.0, 1787306402.0)
    assert hooks.spans[1][2:4] == (1787306402.0, 1787306404.0)
    first_model = hooks.spans[0][4].logs[0]
    assert first_model == {
        "input": [{"role": "user", "content": "find it"}],
        "output": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tool-1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"query": "signals"}'},
                }
            ],
        },
        "metadata": {"model": "claude-haiku-4-5"},
        "metrics": {"prompt_tokens": 10, "completion_tokens": 2, "tokens": 12},
    }
    assert hooks.spans[1][4].logs == [
        {
            "input": {"query": "signals"},
            "output": "found",
            "metadata": {"tool_call_id": "tool-1"},
        }
    ]
