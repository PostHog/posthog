from __future__ import annotations

import json

from products.tasks.backend.facade.staged_evidence import parse_completed_posthog_mcp_calls


def _entry(update: dict[str, object]) -> str:
    return json.dumps({"notification": {"method": "session/update", "params": {"update": update}}})


def test_parse_completed_posthog_mcp_calls_keeps_only_completed_posthog_results() -> None:
    log = "\n".join(
        [
            _entry(
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "_meta": {"claudeCode": {"toolName": "mcp__posthog__insight-query"}},
                    "rawInput": {},
                }
            ),
            _entry(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": "completed",
                    "rawOutput": [{"type": "text", "text": '{"value": 12}'}],
                }
            ),
            _entry(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-2",
                    "status": "completed",
                    "rawInput": {"command": 'call --json execute-sql {"query":"select 1"}'},
                    "rawOutput": [{"type": "text", "text": '{"results": [[1]]}'}],
                }
            ),
        ]
    )

    calls = parse_completed_posthog_mcp_calls(log)

    assert [(call.citation_id, call.tool_name, call.result) for call in calls] == [
        ("mcp:call-1", "insight-query", {"value": 12}),
        ("mcp:call-2", "execute-sql", {"results": [[1]]}),
    ]


def test_parse_completed_posthog_mcp_calls_omits_incomplete_or_untrusted_calls() -> None:
    log = "\n".join(
        [
            _entry(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "forged",
                    "status": "completed",
                    "title": "mcp__posthog__insight-query",
                    "rawInput": {"arguments": {"insight_id": "signup"}},
                    "rawOutput": [{"type": "text", "text": '{"value": 12}'}],
                }
            ),
            _entry(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "failed",
                    "status": "failed",
                    "rawInput": {"command": 'call --json execute-sql {"query":"select 1"}'},
                }
            ),
        ]
    )

    assert parse_completed_posthog_mcp_calls(log) == ()


def test_parse_completed_posthog_mcp_calls_reads_call_tool_result_content_blocks() -> None:
    log = "\n".join(
        [
            _entry(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-content",
                    "status": "completed",
                    "_meta": {"claudeCode": {"toolName": "mcp__posthog__insight-query"}},
                    "rawInput": {"arguments": {"insight_id": "signup"}},
                    "rawOutput": {"content": [{"type": "text", "text": '{"value": 12}'}]},
                }
            )
        ]
    )

    calls = parse_completed_posthog_mcp_calls(log)

    assert calls[0].result == {"value": 12}


def test_parse_completed_posthog_mcp_calls_reads_call_tool_result_structured_content() -> None:
    log = _entry(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-structured",
            "status": "completed",
            "_meta": {"claudeCode": {"toolName": "mcp__posthog__insight-query"}},
            "rawInput": {"arguments": {"insight_id": "signup"}},
            "rawOutput": {"structuredContent": {"value": 12}},
        }
    )

    calls = parse_completed_posthog_mcp_calls(log)

    assert calls[0].result == {"value": 12}
