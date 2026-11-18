"""Builders for ACP JSONL log lines, shared by the log parser, tool chain, and trace event tests."""

from __future__ import annotations

import json


def notification_entry(**params) -> dict:
    return {
        "type": "notification",
        "timestamp": params.pop("ts"),
        "notification": {
            "jsonrpc": "2.0",
            "method": params.pop("method", "session/update"),
            "params": params.pop("params", {}),
        },
    }


def session_update_line(ts: str, update: dict) -> str:
    return json.dumps(notification_entry(ts=ts, method="session/update", params={"sessionId": "s", "update": update}))


def prompt_line(ts: str, text: str = "hello") -> str:
    return json.dumps(
        notification_entry(
            ts=ts,
            method="session/prompt",
            params={"sessionId": "s", "prompt": [{"type": "text", "text": text}]},
        )
    )


def end_turn_line(ts: str, usage: dict | None = None) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": ts,
            "notification": {
                "jsonrpc": "2.0",
                "result": {
                    "stopReason": "end_turn",
                    "usage": usage
                    or {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                },
            },
        }
    )


def tool_call_start_line(ts: str, call_id: str, name: str) -> str:
    return session_update_line(
        ts,
        {
            "sessionUpdate": "tool_call",
            "toolCallId": call_id,
            "status": "pending",
            "rawInput": {},
            "title": name,
            "_meta": {"claudeCode": {"toolName": name}},
        },
    )


def tool_call_input_line(ts: str, call_id: str, raw_input: dict) -> str:
    return session_update_line(
        ts,
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": call_id,
            "status": None,
            "rawInput": raw_input,
        },
    )


def tool_call_completed_line(ts: str, call_id: str, output: str, status: str = "completed") -> str:
    return session_update_line(
        ts,
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": call_id,
            "status": status,
            "rawOutput": output,
        },
    )


def agent_text_line(ts: str, text: str) -> str:
    return session_update_line(
        ts,
        {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}},
    )


def join_lines(lines: list[str]) -> str:
    return "\n".join(lines)
