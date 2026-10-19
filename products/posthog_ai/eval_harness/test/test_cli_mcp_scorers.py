from __future__ import annotations

import json

from parameterized import parameterized

from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.posthog_ai.evals.cli_mcp.scorers import (
    INLINE_VIEW_NOTE,
    ChartFromTypedQuery,
    ChartShown,
    DidNotCiteRawSqlAfterTypedQuery,
    FirstRelevantTool,
    NoAnalyticsSql,
    NoMarkdownDataTable,
)


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
    assert result.name == "first_relevant_tool"


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


def _multi_turn_output(turn_commands: list[str], *, turn_index: int, total_turns: int = 4) -> dict:
    """Build the runner's multi-turn output shape, with a real log only in one slice.

    Each slice carries distinct SQL so the process-wide ``LogParser.cached`` key
    never collides across parameterizations. ``turn_index`` is 0-based.
    """
    turn_logs = [f'{{"filler-turn": {i}}}' for i in range(total_turns)]
    turn_logs[turn_index] = _raw_log([[turn_commands[turn_index]]])
    return {
        "raw_log": turn_logs[turn_index],
        "prompt": "turn 1 prompt",
        "turn_logs": turn_logs,
        "turn_prompts": [f"turn {i + 1} prompt" for i in range(total_turns)],
    }


@parameterized.expand(
    [
        ("turn3_recovers_to_typed", 2, "call query-trends {}", "query-trends", 1.0),
        ("turn3_stays_on_sql", 2, _sql_command(_ANSWER_SQL), "query-trends", 0.0),
        ("turn2_sql_matches_its_override", 1, _sql_command(_ANSWER_SQL), "execute-sql", 1.0),
    ]
)
def test_first_relevant_tool_grades_a_single_turn(
    _name: str, turn_index: int, command: str, target: str, expected_score: float
) -> None:
    commands = [command] * 4
    output = _multi_turn_output(commands, turn_index=turn_index)

    result = FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS, turn=turn_index + 1, tool=target)._run_eval_sync(
        output,
        expected={"first_relevant_tool": {"tool": "query-trends"}},
    )

    assert result.score == expected_score
    # A distinct name per turn keeps the four per-turn scores from colliding on
    # one key in the per-case export and the rollup.
    assert result.name == f"first_relevant_tool_t{turn_index + 1}"


def test_first_relevant_tool_turn_reads_expected_tool_without_override() -> None:
    output = _multi_turn_output(["call query-trends {}"] * 4, turn_index=2)

    result = FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS, turn=3)._run_eval_sync(
        output,
        expected={"first_relevant_tool": {"tool": "query-trends"}},
    )

    assert result.score == 1.0
    # Name diverges by turn, but the expected lookup still resolves under the
    # shared base key.
    assert result.name == "first_relevant_tool_t3"


def test_first_relevant_tool_turn_skips_a_missing_slice() -> None:
    output = _multi_turn_output(["call query-trends {}"] * 4, turn_index=2)

    result = FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS, turn=9)._run_eval_sync(
        output,
        expected={"first_relevant_tool": {"tool": "query-trends"}},
    )

    assert result.score is None
    assert "No turn 9 log slice" in result.metadata["reason"]


_TRENDS_RESULT = ("mcp__posthog__query-trends", {"series": []}, "rows")
_TRENDS_INLINE_RESULT = ("mcp__posthog__query-trends", {"series": []}, f"rows\n\nThe user {INLINE_VIEW_NOTE}.")
_BASE = "https://us.example.com/project/1"
_SQL_CHART = f"[Weekly signups]({_BASE}/sql?open_query=SELECT%20toStartOfWeek(timestamp)%2C%20count()%20FROM%20events)"
_INSIGHT_CHART = f"[Weekly signups]({_BASE}/insights/9pQx3)"
_UNSAVED_INSIGHT_LINK = f"[Weekly signups]({_BASE}/insights/new#q=%7B%7D)"


def _render(tool_name: str, status: str = "completed") -> tuple:
    return ("mcp__posthog__render-ui", {"tool_name": tool_name, "tool_input": {}}, "Rendering", status)


def _chart_output(calls: list[tuple], answer: str = "Signups rose.") -> dict:
    return {
        "raw_log": _raw_tool_log(calls),
        "prompt": "Weekly signups",
        "messages": [{"role": "assistant", "content": [{"type": "text", "text": answer}]}],
    }


@parameterized.expand(
    [
        ("rendered_query_tool", [_TRENDS_RESULT, _render("query-trends")], "Signups rose.", 1.0, 1.0),
        ("inline_view_note", [_TRENDS_INLINE_RESULT], "Signups rose.", 1.0, 1.0),
        ("saved_insight_link", [_TRENDS_RESULT], f"Signups rose.\n\n{_INSIGHT_CHART}\n\nMore text.", 1.0, 1.0),
        ("sql_link_after_typed_query", [_TRENDS_RESULT], f"Signups rose.\n\n{_SQL_CHART}", 1.0, 0.0),
        ("sql_link_inside_sentence", [_TRENDS_RESULT], f"See {_SQL_CHART} for details.", 0.0, None),
        ("unsaved_insight_link", [_TRENDS_RESULT], f"Signups rose.\n\n{_UNSAVED_INSIGHT_LINK}", 0.0, None),
        ("failed_render", [_TRENDS_RESULT, _render("query-trends", status="failed")], "Signups rose.", 0.0, None),
        ("rendered_other_tool", [_TRENDS_RESULT, _render("experiment-list")], "Signups rose.", 0.0, None),
    ]
)
def test_chart_scorers_grade_each_chart_path(
    _name: str, calls: list[tuple], answer: str, shown: float, typed: float | None
) -> None:
    output = _chart_output(calls, answer)
    spec = {"tool_name_any_of": ["query-trends"]}

    assert ChartShown()._run_eval_sync(output, expected={"chart_shown": spec}).score == shown
    assert ChartFromTypedQuery()._run_eval_sync(output, expected={"chart_from_typed_query": spec}).score == typed


_LONG_TABLE = "| Week | Signups |\n|---|---|\n| W1 | 10 |\n| W2 | 12 |\n| W3 | 9 |\n| W4 | 14 |"
_SUMMARY_TABLE = "| Period | Signups |\n| :--- | ---: |\n| Last 7 days | 45 |\n| Previous 7 days | 38 |"


@parameterized.expand(
    [
        ("long_table", [f"Signups rose.\n\n{_LONG_TABLE}\n\nThey peaked in W4."], 0.0),
        ("long_table_before_closing_line", [f"Signups rose.\n\n{_LONG_TABLE}", "I added two buttons above."], 0.0),
        ("summary_table", [f"Signups rose 18%.\n\n{_SUMMARY_TABLE}"], 1.0),
        ("prose_with_pipes", ["Signups rose 18% | weekly peak in W4 | no drop."], 1.0),
    ]
)
def test_no_markdown_data_table_flags_long_tables(_name: str, texts: list[str], score: float) -> None:
    messages = [{"role": "assistant", "content": [{"type": "text", "text": text}]} for text in texts]

    result = NoMarkdownDataTable()._run_eval_sync(
        {"messages": messages, "last_message": texts[-1]}, expected={"no_markdown_data_table": {}}
    )

    assert result.score == score


def _sql(query: str) -> tuple:
    return ("mcp__posthog__execute-sql", {"query": query}, "rows")


@parameterized.expand(
    [
        ("typed_only", [_TRENDS_RESULT], 1.0),
        (
            "catalog_lookup_then_typed",
            [_sql("SELECT id, name FROM system.insights WHERE name ILIKE '%x%'"), _TRENDS_RESULT],
            1.0,
        ),
        ("catalog_cte", [_sql("WITH a AS (SELECT id FROM system.actions) SELECT count() FROM a")], 1.0),
        ("events_sql", [_sql("SELECT count() FROM events WHERE event = 'signed_up'")], 0.0),
        (
            "typed_then_events_sql",
            [_TRENDS_RESULT, _sql("SELECT toStartOfWeek(timestamp), count() FROM events GROUP BY 1")],
            0.0,
        ),
        ("join_to_events", [_sql("SELECT i.name FROM system.insights i JOIN events e ON e.uuid = i.id")], 0.0),
    ]
)
def test_no_analytics_sql_allows_only_catalog_lookups(_name: str, calls: list[tuple], score: float) -> None:
    result = NoAnalyticsSql()._run_eval_sync(
        {"raw_log": _raw_tool_log(calls), "prompt": "Weekly signups"}, expected={"no_analytics_sql": {}}
    )

    assert result.score == score
