from __future__ import annotations

import json

import pytest

from products.posthog_ai.eval_harness.acp_log import parse_log


def _line(payload: dict) -> str:
    return json.dumps({"type": "notification", "timestamp": "2026-04-29T08:42:29.620Z", "notification": payload})


@pytest.mark.parametrize(
    "lines, expected_model",
    [
        pytest.param(
            [
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "session/new",
                        "params": {"model": "anthropic/claude-opus-4-7"},
                    }
                ),
            ],
            "anthropic/claude-opus-4-7",
            id="captures_from_session_new_params",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": "/tmp"}}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"sessionId": "s1", "models": {"currentModelId": "claude-sonnet-4-6"}},
                    }
                ),
            ],
            "claude-sonnet-4-6",
            id="falls_back_to_result_currentModelId",
        ),
        pytest.param(
            [
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "session/new",
                        "params": {"model": "anthropic/claude-opus-4-7"},
                    }
                ),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"sessionId": "s1", "models": {"currentModelId": "claude-sonnet-4-6"}},
                    }
                ),
            ],
            "anthropic/claude-opus-4-7",
            id="prefers_params_over_result_when_both_present",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/prompt", "params": {}}),
            ],
            "",
            id="empty_when_no_session_new",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"model": ""}}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"sessionId": "s1", "models": {"currentModelId": "claude-haiku-4-5"}},
                    }
                ),
            ],
            "claude-haiku-4-5",
            id="ignores_empty_string_model_and_falls_back",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": "/tmp"}}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "sessionId": "s1",
                            "configOptions": [
                                {"type": "select", "id": "mode", "category": "mode", "currentValue": "auto"},
                                {"type": "select", "id": "model", "category": "model", "currentValue": "gpt-5.5"},
                                {"type": "select", "id": "effort", "category": "thought_level", "currentValue": "low"},
                            ],
                        },
                    }
                ),
            ],
            "gpt-5.5",
            id="falls_back_to_config_options_model_entry",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": "/tmp"}}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "sessionId": "s1",
                            "models": {"currentModelId": "claude-sonnet-4-6"},
                            "configOptions": [{"type": "select", "id": "model", "currentValue": "gpt-5.5"}],
                        },
                    }
                ),
            ],
            "claude-sonnet-4-6",
            id="prefers_current_model_id_over_config_options",
        ),
    ],
)
def test_parse_log_extracts_agent_model(lines: list[str], expected_model: str) -> None:
    parsed = parse_log("\n".join(lines))
    assert parsed.model == expected_model


def _tool_call_line(meta: dict | None, title: str) -> str:
    return _line(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "t1",
                    "title": title,
                    "_meta": meta,
                    "rawInput": {},
                }
            },
        }
    )


@pytest.mark.parametrize(
    "meta, title, expected_name",
    [
        pytest.param(
            {"claudeCode": {"toolName": "mcp__posthog__execute_sql"}},
            "execute sql",
            "mcp__posthog__execute_sql",
            id="claude_runtime_meta",
        ),
        pytest.param(
            {"posthog": {"toolName": "mcp__posthog__exec", "mcp": {"server": "posthog", "tool": "exec"}}},
            "posthog/exec",
            "mcp__posthog__exec",
            id="codex_runtime_meta",
        ),
        pytest.param(None, "/bin/bash -lc ls", "/bin/bash -lc ls", id="null_meta_falls_back_to_title"),
        pytest.param({"posthog": {}}, "posthog/exec", "posthog/exec", id="empty_adapter_meta_falls_back_to_title"),
    ],
)
def test_parse_log_resolves_tool_name_from_runtime_meta(meta: dict | None, title: str, expected_name: str) -> None:
    parsed = parse_log(_tool_call_line(meta, title))
    tool_uses = [
        block
        for message in parsed.messages
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_use"
    ]
    assert [block["name"] for block in tool_uses] == [expected_name]


def _tool_call_update_line(status: str, extra: dict) -> str:
    return _line(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": status, **extra}},
        }
    )


def _text_block(text: str) -> dict:
    return {"type": "content", "content": {"type": "text", "text": text}}


@pytest.mark.parametrize(
    "status, extra, expected_content, expected_is_error",
    [
        pytest.param(
            "completed",
            {"content": [_text_block("42 rows")]},
            "42 rows",
            False,
            id="codex_content_list",
        ),
        pytest.param(
            "completed",
            {"content": [_text_block("first"), _text_block("second")]},
            "first\nsecond",
            False,
            id="joins_multiple_content_blocks",
        ),
        pytest.param(
            "completed",
            {"content": [_text_block("ignored")], "rawOutput": {"success": True}},
            json.dumps({"success": True}),
            False,
            id="raw_output_wins_over_content_list",
        ),
        pytest.param(
            "failed",
            {"content": [_text_block("boom")]},
            "boom",
            True,
            id="failed_status_extracts_error_text",
        ),
        pytest.param(
            "completed",
            {"content": [{"type": "diff", "path": "a.txt", "oldText": "old", "newText": "new"}]},
            "[diff] a.txt",
            False,
            id="diff_blocks_render_as_path_marker",
        ),
        pytest.param("completed", {}, "(no output)", False, id="missing_output_keeps_placeholder"),
    ],
)
def test_parse_log_extracts_tool_result_from_content_list(
    status: str, extra: dict, expected_content: str, expected_is_error: bool
) -> None:
    lines = [_tool_call_line(None, "posthog/exec"), _tool_call_update_line(status, extra)]
    parsed = parse_log("\n".join(lines))
    tool_results = [
        block
        for message in parsed.messages
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1
    assert tool_results[0]["content"] == expected_content
    assert tool_results[0].get("is_error", False) is expected_is_error


def _agent_message_line(text: str) -> str:
    return _line(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}}},
        }
    )


@pytest.mark.parametrize(
    "lines, expected_usages",
    [
        pytest.param(
            [
                _agent_message_line("checking"),
                _tool_call_line({"posthog": {"toolName": "mcp__posthog__exec"}}, "posthog/exec"),
                _tool_call_update_line("completed", {"content": [_text_block("42 rows")]}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "method": "_posthog/usage_update",
                        "params": {
                            "sessionId": "s1",
                            "usage": {
                                "inputTokens": 100,
                                "outputTokens": 20,
                                "cachedReadTokens": 5,
                                "reasoningTokens": 3,
                                "totalTokens": 120,
                            },
                        },
                    }
                ),
                _agent_message_line("done"),
                _line({"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}),
            ],
            [
                {
                    "inputTokens": 100,
                    "outputTokens": 20,
                    "cachedReadTokens": 5,
                    "cachedWriteTokens": 0,
                    "totalTokens": 120,
                    "reasoningTokens": 3,
                },
                {},
            ],
            id="codex_usage_update_attaches_to_flushed_generation",
        ),
        pytest.param(
            [
                _agent_message_line("done"),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {"stopReason": "end_turn", "usage": {"inputTokens": 50, "outputTokens": 10}},
                    }
                ),
            ],
            [
                {
                    "inputTokens": 50,
                    "outputTokens": 10,
                    "cachedReadTokens": 0,
                    "cachedWriteTokens": 0,
                    "totalTokens": 0,
                }
            ],
            id="claude_result_usage_still_wins",
        ),
        pytest.param(
            [
                _agent_message_line("done"),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "method": "_posthog/usage_update",
                        "params": {"sessionId": "s1", "used": {"inputTokens": 50}, "cost": 0.75},
                    }
                ),
                _line({"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}),
            ],
            [{}],
            id="claude_usage_update_without_usage_key_is_ignored",
        ),
    ],
)
def test_parse_log_attaches_token_usage_per_generation(lines: list[str], expected_usages: list[dict]) -> None:
    parsed = parse_log("\n".join(lines))
    assert [gen.token_usage for gen in parsed.generations] == expected_usages
