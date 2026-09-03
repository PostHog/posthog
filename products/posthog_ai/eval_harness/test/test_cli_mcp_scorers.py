from __future__ import annotations

import json

from parameterized import parameterized

from products.posthog_ai.evals.cli_mcp.scorers import DidNotCiteRawSqlAfterTypedQuery, FirstRelevantTool


def _tool_call_start(call_id: str, command: str) -> str:
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": call_id,
                        "rawInput": {"command": command},
                        "_meta": {"claudeCode": {"toolName": "mcp__posthog__exec"}},
                    }
                },
            }
        }
    )


def _tool_call_result(call_id: str) -> str:
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": call_id,
                        "status": "completed",
                        "rawOutput": "ok",
                    }
                },
            }
        }
    )


def _tool_call(call_id: str, command: str) -> list[str]:
    return [_tool_call_start(call_id, command), _tool_call_result(call_id)]


def _raw_log(turns: list[list[str]]) -> str:
    """Render one assistant turn per inner list of commands.

    The parser opens a new assistant message when a tool call follows a
    captured result, so emitting every call of a turn before any of its
    results is what gives those calls one shared position.
    """
    lines: list[str] = []
    for turn_index, commands in enumerate(turns):
        call_ids = [f"call-{turn_index}-{index}" for index in range(len(commands))]
        lines += [_tool_call_start(call_id, command) for call_id, command in zip(call_ids, commands)]
        lines += [_tool_call_result(call_id) for call_id in call_ids]
    return "\n".join(lines)


ANALYSIS_QUERY_TOOLS = frozenset({"query-trends", "query-funnel", "query-retention", "execute-sql"})

_DISCOVERY_SQL = "SELECT column_name FROM system.information_schema.columns WHERE table_name = 'events'"
_ANSWER_SQL = "SELECT count() FROM events WHERE event = 'logged_in'"


def _sql_command(query: str) -> str:
    payload = json.dumps({"query": query})
    return f"call execute-sql {payload}"


@parameterized.expand(
    [
        (
            "typed_query_first_then_sql",
            [["call query-retention {}"], [_sql_command(_ANSWER_SQL)]],
            "query-retention",
            1.0,
            ["query-retention"],
        ),
        (
            "sql_answer_before_the_typed_query",
            [[_sql_command(_ANSWER_SQL)], ["call query-retention {}"]],
            "query-retention",
            0.0,
            ["execute-sql"],
        ),
        (
            "mandated_catalog_lookup_before_the_typed_query",
            [[_sql_command(_DISCOVERY_SQL)], ["call query-retention {}"]],
            "query-retention",
            1.0,
            ["query-retention"],
        ),
        (
            "sql_control_that_only_looked_up_the_catalog",
            [[_sql_command(_DISCOVERY_SQL)]],
            "execute-sql",
            0.0,
            None,
        ),
        (
            "typed_query_and_sql_in_one_turn_fails_the_typed_case",
            [["call query-retention {}", _sql_command(_ANSWER_SQL)]],
            "query-retention",
            0.0,
            ["execute-sql", "query-retention"],
        ),
        (
            "typed_query_and_sql_in_one_turn_fails_the_sql_control",
            [[_sql_command(_ANSWER_SQL), "call query-retention {}"]],
            "execute-sql",
            0.0,
            ["execute-sql", "query-retention"],
        ),
    ]
)
def test_first_relevant_tool_grades_the_answer_route(
    _name: str,
    turns: list[list[str]],
    target: str,
    expected_score: float,
    expected_turn_tools: list[str] | None,
) -> None:
    result = FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS)._run_eval_sync(
        {"raw_log": _raw_log(turns)},
        expected={"first_relevant_tool": {"tool": target}},
    )

    assert result.score == expected_score
    assert result.metadata.get("first_relevant_tools") == expected_turn_tools


@parameterized.expand(
    [
        ("hogql_tag", 'Here is the trend: <hogql label="pageviews">SELECT count() FROM events</hogql>'),
        ("sql_fence", "Here is the trend:\n```sql\nSELECT count() FROM events\n```"),
    ]
)
def test_did_not_cite_raw_sql_fails_when_answer_hand_writes_sql_after_typed_query(
    _name: str, last_message: str
) -> None:
    raw_log = "\n".join(_tool_call("trends", "call query-trends {}"))

    result = DidNotCiteRawSqlAfterTypedQuery()._run_eval_sync(
        {"raw_log": raw_log, "last_message": last_message},
        expected={"did_not_cite_raw_sql_after_typed_query": {"tool": "query-trends"}},
    )

    assert result.score == 0.0


def test_did_not_cite_raw_sql_passes_when_answer_trusts_the_tool_result() -> None:
    raw_log = "\n".join(_tool_call("trends", "call query-trends {}"))

    result = DidNotCiteRawSqlAfterTypedQuery()._run_eval_sync(
        {"raw_log": raw_log, "last_message": "Pageviews were up 12% over the last 7 days."},
        expected={"did_not_cite_raw_sql_after_typed_query": {"tool": "query-trends"}},
    )

    assert result.score == 1.0


def test_did_not_cite_raw_sql_is_none_when_the_typed_tool_was_never_called() -> None:
    raw_log = "\n".join(_tool_call("sql", "call execute-sql {}"))

    result = DidNotCiteRawSqlAfterTypedQuery()._run_eval_sync(
        {"raw_log": raw_log, "last_message": "<hogql>SELECT count() FROM events</hogql>"},
        expected={"did_not_cite_raw_sql_after_typed_query": {"tool": "query-trends"}},
    )

    assert result.score is None
