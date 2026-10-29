from __future__ import annotations

from products.posthog_ai.eval_harness.test.test_log_parser import (
    _agent_text,
    _end_turn,
    _join,
    _prompt,
    _tool_call_completed,
    _tool_call_input,
    _tool_call_start,
)
from products.posthog_ai.eval_harness.tool_chain import build_tool_chain, render_tool_chain, summarize_tool_chain

_SCHEMA_QUERY = "SELECT name FROM system.information_schema.tables"
_ANSWER_QUERY = "SELECT count() FROM events WHERE event = 'uploaded_file'"


def _turn_one() -> list[str]:
    # Two calls in one assistant message: both tool_call lines arrive before either result.
    return [
        _prompt("2026-04-15T10:00:00.000Z"),
        _tool_call_start("2026-04-15T10:00:01.000Z", "schema", "mcp__posthog__execute-sql"),
        _tool_call_start("2026-04-15T10:00:01.050Z", "slack", "mcp__slack__search_messages"),
        _tool_call_input("2026-04-15T10:00:01.100Z", "schema", {"query": _SCHEMA_QUERY}),
        _tool_call_input("2026-04-15T10:00:01.150Z", "slack", {"query": "pre-tax"}),
        _tool_call_completed("2026-04-15T10:00:02.500Z", "schema", "events"),
        _tool_call_completed("2026-04-15T10:00:04.050Z", "slack", "no match", status="failed"),
        _agent_text("2026-04-15T10:00:05.000Z", "checking"),
        _end_turn("2026-04-15T10:00:06.000Z"),
    ]


def _turn_two() -> list[str]:
    return [
        _prompt("2026-04-15T10:01:00.000Z", "and uploads?"),
        _tool_call_start("2026-04-15T10:01:01.000Z", "answer", "mcp__posthog__execute-sql"),
        _tool_call_input("2026-04-15T10:01:01.100Z", "answer", {"query": _ANSWER_QUERY}),
        _tool_call_completed("2026-04-15T10:01:03.000Z", "answer", "42"),
        _agent_text("2026-04-15T10:01:04.000Z", "42 uploads"),
        _end_turn("2026-04-15T10:01:05.000Z"),
    ]


def test_tool_chain_orders_parallel_calls_and_assigns_turns() -> None:
    turn_logs = [_join(_turn_one()), _join(_turn_two())]
    output = {"raw_log": _join(_turn_one() + _turn_two()), "prompt": "how many uploads?", "turn_logs": turn_logs}

    chain = build_tool_chain(output)

    assert [(step.sequence, step.name, step.server, step.turn) for step in chain] == [
        (0, "execute-sql", "posthog", 0),
        (1, "search_messages", "slack", 0),
        (2, "execute-sql", "posthog", 1),
    ]
    assert [step.duration_seconds for step in chain] == [1.5, 3.0, 2.0]
    assert chain[1].is_error
    assert summarize_tool_chain(chain) == {
        "tool_count": 3,
        "distinct_tools": ["execute-sql", "search_messages"],
        "discovery_calls": 1,
        "answer_calls": 1,
        "errors": 1,
        "first_answer_sequence": 2,
        "servers": ["posthog", "slack"],
    }
    assert render_tool_chain(chain).splitlines() == [
        f"1. execute-sql({_SCHEMA_QUERY}) -> events",
        '2. search_messages({"query":"pre-tax"}) -> ERROR no match',
        f"3. execute-sql({_ANSWER_QUERY}) -> 42",
    ]


def test_tool_chain_keeps_skill_calls_and_classifies_long_discovery_queries() -> None:
    # The table name sits past the digest limit, so only the full query shows that this is a lookup.
    long_lookup = (
        "SELECT " + ", ".join(f"column_{index}" for index in range(40)) + " FROM system.information_schema.columns"
    )
    lines = [
        _prompt("2026-04-15T10:00:00.000Z"),
        _tool_call_start("2026-04-15T10:00:01.000Z", "skill", "Skill"),
        _tool_call_input("2026-04-15T10:00:01.100Z", "skill", {"skill": "querying-posthog-data"}),
        _tool_call_completed("2026-04-15T10:00:02.000Z", "skill", "loaded"),
        _tool_call_start("2026-04-15T10:00:03.000Z", "lookup", "mcp__posthog__execute-sql"),
        _tool_call_input("2026-04-15T10:00:03.100Z", "lookup", {"query": long_lookup}),
        _tool_call_completed("2026-04-15T10:00:04.000Z", "lookup", "columns"),
        _agent_text("2026-04-15T10:00:05.000Z", "done"),
        _end_turn("2026-04-15T10:00:06.000Z"),
    ]

    chain = build_tool_chain({"raw_log": _join(lines), "prompt": "which columns?"})

    assert [step.raw_name for step in chain] == ["Skill", "mcp__posthog__execute-sql"]
    summary = summarize_tool_chain(chain)
    assert (summary["discovery_calls"], summary["answer_calls"]) == (1, 0)
