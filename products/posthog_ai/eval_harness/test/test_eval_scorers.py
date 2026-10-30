from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from products.posthog_ai.eval_harness.log_parser import SKILL_TOOL_NAME
from products.posthog_ai.eval_harness.scorers import (
    AnswerToolCallNot,
    ServerUsed,
    SourcesAvoided,
    SourcesConsulted,
    ToolMatch,
    ToolOrder,
)
from products.posthog_ai.evals.error_tracking.scorers import (
    ERROR_TRACKING_WRITE_TOOLS,
    QUERY_ISSUE_EVENTS_TOOL,
    QUERY_ISSUES_LIST_TOOL,
    EventsToolUsed,
    IssueDrilldownOrder,
    IssuesListToolUsed,
    _recordings_text_has_results,
)
from products.posthog_ai.evals.retrieval.scorers import SkillTriggered


def _raw_tool_log(calls: Sequence[tuple[Any, ...]]) -> str:
    """Build an ACP log. A fourth tuple element overrides the result status.

    ``"failed"`` is what makes ``ToolCall.is_error`` true, which every scorer here
    uses to ignore an attempt the agent made and lost.
    """
    lines = []
    for index, call in enumerate(calls, start=1):
        name, raw_input, raw_output = call[0], call[1], call[2]
        result_status = call[3] if len(call) > 3 else "completed"
        call_id = f"call-{index}"
        lines.append(
            {
                "timestamp": f"2026-01-01T00:00:{index:02d}Z",
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": call_id,
                            "title": name,
                            "rawInput": raw_input,
                            "_meta": {"claudeCode": {"toolName": name}},
                        }
                    },
                },
            }
        )
        lines.append(
            {
                "timestamp": f"2026-01-01T00:00:{index:02d}Z",
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": call_id,
                            "status": result_status,
                            "rawOutput": raw_output,
                        }
                    },
                },
            }
        )
    return "\n".join(json.dumps(line) for line in lines)


def test_write_tool_blocklist_includes_enabled_rule_update_tools() -> None:
    assert {
        "error-tracking-grouping-rules-update",
        "error-tracking-suppression-rules-update",
    }.issubset(ERROR_TRACKING_WRITE_TOOLS)


def test_recordings_text_has_results_accepts_toon_lists() -> None:
    assert _recordings_text_has_results(
        """
results[1]:
  - id: 019e4f6a-b3d7-7000-8a3a-f18fc1f9d80a
    session_id: session-1
hasMore: false
"""
    )


def test_recordings_text_has_results_rejects_empty_toon_lists() -> None:
    assert not _recordings_text_has_results(
        """
results:
hasMore: false
"""
    )


def test_events_tool_used_rejects_empty_results() -> None:
    score = EventsToolUsed()._run_eval_sync(
        {
            "raw_log": _raw_tool_log(
                [(QUERY_ISSUE_EVENTS_TOOL, {"issueId": "issue-1"}, {"results": [], "hasMore": False})]
            )
        }
    )

    assert score.score == 0.0
    assert score.metadata["reason"] == f"{QUERY_ISSUE_EVENTS_TOOL} returned no sampled events"


def test_issues_list_tool_used_rejects_empty_results() -> None:
    score = IssuesListToolUsed()._run_eval_sync(
        {
            "raw_log": _raw_tool_log(
                [(QUERY_ISSUES_LIST_TOOL, {"searchQuery": "TypeError"}, {"results": [], "hasMore": False})]
            )
        }
    )

    assert score.score == 0.0
    assert score.metadata["reason"] == f"{QUERY_ISSUES_LIST_TOOL} returned no issues"


def test_issue_drilldown_order_requires_non_empty_events() -> None:
    score = IssueDrilldownOrder()._run_eval_sync(
        {
            "raw_log": _raw_tool_log(
                [
                    (QUERY_ISSUES_LIST_TOOL, {}, {"results": [{"id": "issue-1"}], "hasMore": False}),
                    (QUERY_ISSUE_EVENTS_TOOL, {"issueId": "issue-1"}, {"results": [], "hasMore": False}),
                ]
            )
        },
        {"drilldown": {"requires_issue": False, "requires_events": True}},
    )

    assert score.score == 0.0
    assert score.metadata["reason"] == f"{QUERY_ISSUE_EVENTS_TOOL} returned no sampled events"


def test_issue_drilldown_order_accepts_non_empty_events() -> None:
    score = IssueDrilldownOrder()._run_eval_sync(
        {
            "raw_log": _raw_tool_log(
                [
                    (QUERY_ISSUES_LIST_TOOL, {}, {"results": [{"id": "issue-1"}], "hasMore": False}),
                    (
                        QUERY_ISSUE_EVENTS_TOOL,
                        {"issueId": "issue-1"},
                        {"results": [{"uuid": "event-1"}], "hasMore": False},
                    ),
                ]
            )
        },
        {"drilldown": {"requires_issue": False, "requires_events": True}},
    )

    assert score.score == 1.0


_SKILL = "instrument-feature-flags"


@pytest.mark.parametrize(
    "load_call,should_load,expected_score",
    [
        ((SKILL_TOOL_NAME, {"skill": _SKILL}), True, 1.0),
        (("Read", {"file_path": f"/root/.claude/skills/{_SKILL}/SKILL.md"}), True, 1.0),
        (("Bash", {"command": f"cat /scripts/plugins/posthog/skills/{_SKILL}/SKILL.md"}), True, 1.0),
        (None, False, 1.0),
        (None, True, 0.0),
        ((SKILL_TOOL_NAME, {"skill": _SKILL}), False, 0.0),
    ],
)
def test_skill_triggered_grades_against_the_expected_direction(
    load_call: tuple[str, dict[str, Any]] | None, should_load: bool, expected_score: float
) -> None:
    calls: list[tuple[str, dict[str, Any], object]] = [("Read", {"file_path": "src/app/page.tsx"}, "ok")]
    if load_call is not None:
        calls.append((*load_call, "loaded"))

    score = SkillTriggered(_SKILL, name="trigger")._run_eval_sync(
        {"raw_log": _raw_tool_log(calls)},
        {"trigger": {"should_load": should_load}},
    )

    assert score.score == expected_score
    assert score.metadata["loaded"] is (load_call is not None)


@pytest.mark.parametrize(
    "load_call",
    [
        (SKILL_TOOL_NAME, {"skill": _SKILL}),
        ("Read", {"file_path": f"/root/.claude/skills/{_SKILL}/SKILL.md"}),
        ("Bash", {"command": f"cat /scripts/plugins/posthog/skills/{_SKILL}/SKILL.md"}),
    ],
)
def test_skill_triggered_ignores_a_failed_load_attempt(load_call: tuple[str, dict[str, Any]]) -> None:
    score = SkillTriggered(_SKILL, name="trigger")._run_eval_sync(
        {"raw_log": _raw_tool_log([(*load_call, "boom", "failed")])},
        {"trigger": {"should_load": False}},
    )

    assert score.score == 1.0
    assert score.metadata["loaded"] is False


@pytest.mark.parametrize("expected", [None, {}, {"trigger": {}}, {"trigger": None}])
def test_skill_triggered_skips_when_the_case_declares_no_direction(expected: dict | None) -> None:
    score = SkillTriggered(_SKILL, name="trigger")._run_eval_sync(
        {"raw_log": _raw_tool_log([(SKILL_TOOL_NAME, {"skill": _SKILL}, "loaded")])},
        expected,
    )

    assert score.score is None


@pytest.mark.parametrize(
    "calls,expected_score,expected_answer_tool",
    [
        # Typed answer followed by an execute-sql validation call: the typed
        # tool wins, the trailing SQL is validation. Reading only the last
        # call instead of the answer scored this 0.
        (
            [
                ("query-trends", {"query": {}}, {"results": []}),
                ("execute-sql", {"query": "SELECT count() FROM events"}, "1"),
            ],
            1.0,
            "query-trends",
        ),
        # execute-sql as the only answer-producing call: it is the answer.
        ([("execute-sql", {"query": "SELECT count() FROM events"}, "1")], 0.0, "execute-sql"),
        # Typed answer, no trailing SQL.
        ([("query-trends", {"query": {}}, {"results": []})], 1.0, "query-trends"),
        # information_schema discovery is not answer-producing and is dropped.
        (
            [
                ("execute-sql", {"query": "SELECT * FROM system.information_schema.tables"}, "t"),
                ("query-trends", {"query": {}}, {"results": []}),
            ],
            1.0,
            "query-trends",
        ),
        # Two typed answers: the last typed call is the answer.
        (
            [
                ("query-funnel", {"query": {}}, {"results": []}),
                ("query-trends", {"query": {}}, {"results": []}),
            ],
            1.0,
            "query-trends",
        ),
        # Intermediary calls after the typed answer never become the answer.
        (
            [
                ("query-trends", {"query": {}}, {"results": []}),
                ("read-data-schema", {"kind": "events"}, "ok"),
                ("exec", {"command": "search"}, "ok"),
            ],
            1.0,
            "query-trends",
        ),
        # execute-sql answer followed by an intermediary call: the SQL is
        # still the answer, the intermediary is ignored.
        (
            [
                ("execute-sql", {"query": "SELECT count() FROM events"}, "1"),
                ("read-data-schema", {"kind": "events"}, "ok"),
            ],
            0.0,
            "execute-sql",
        ),
        # Any typed query-* runner counts, not only trends/funnel: a runner
        # outside the original four (web analytics here) is still
        # answer-producing, so it scores as the answer rather than being skipped.
        ([("query-web-stats", {"query": {}}, {"results": []})], 1.0, "query-web-stats"),
    ],
)
def test_answer_tool_call_not_reads_answer_not_last_call(
    calls: list[tuple], expected_score: float, expected_answer_tool: str
) -> None:
    score = AnswerToolCallNot(forbidden="execute-sql", preferred={"query-trends", "query-funnel"})._run_eval_sync(
        {"raw_log": _raw_tool_log(calls)}
    )

    assert score.score == expected_score
    assert score.metadata["answer_tool_call"] == expected_answer_tool


@pytest.mark.parametrize(
    "calls",
    [
        # Only schema-discovery SQL ran: no answer-producing call.
        [("execute-sql", {"query": "SELECT * FROM system.information_schema.tables"}, "t")],
        # Only intermediary (non-query) calls ran: no answer-producing call.
        [("read-data-schema", {"kind": "events"}, "ok"), ("exec", {"command": "search"}, "ok")],
    ],
)
def test_answer_tool_call_not_skips_when_nothing_answer_producing_ran(calls: list[tuple]) -> None:
    score = AnswerToolCallNot(forbidden="execute-sql", preferred={"query-trends"})._run_eval_sync(
        {"raw_log": _raw_tool_log(calls)}
    )

    assert score.score is None


_METRIC_LIST: tuple[str, dict[str, Any], str] = ("metric-list", {}, "mrr")
_SQL_ANSWER = ("execute-sql", {"query": "SELECT sum(amount_usd) FROM crm_deals"}, "10")


@pytest.mark.parametrize(
    "calls,expected_score",
    [
        ([_METRIC_LIST, _SQL_ANSWER], 1.0),
        ([_SQL_ANSWER, _METRIC_LIST], 0.0),
        # A failed lookup is not a lookup.
        ([("metric-list", {}, "boom", "failed"), _SQL_ANSWER], 0.0),
        # Schema discovery SQL does not match the guarded data query pattern.
        ([("execute-sql", {"query": "SELECT * FROM system.information_schema.tables"}, "t"), _METRIC_LIST], None),
    ],
)
def test_tool_order_requires_the_lookup_before_the_guarded_call(
    calls: list[tuple], expected_score: float | None
) -> None:
    scorer = ToolOrder(
        before=ToolMatch(names=frozenset({"metric-list"})),
        after=ToolMatch(names=frozenset({"execute-sql"}), query_pattern=r"\bfrom\s+crm_deals\b"),
        name="catalog_before_sql",
    )

    assert scorer._run_eval_sync({"raw_log": _raw_tool_log(calls)}).score == expected_score


@pytest.mark.parametrize(
    "calls,spec,expected_score",
    [
        ([_SQL_ANSWER], {"tables": ["crm_deals", "slack_messages"]}, 0.5),
        # A name inside a string literal is a catalog filter, and a longer table name is a different table.
        (
            [
                ("execute-sql", {"query": "SELECT * FROM crm_deals_v3 WHERE note = 'crm_deals'"}, "0"),
                ("execute-sql", {"query": "SELECT * FROM system.information_schema.tables"}, "crm_deals"),
            ],
            {"tables": ["crm_deals"]},
            0.0,
        ),
        ([("execute-sql", {"query": "SELECT * FROM crm_deals"}, "boom", "failed")], {"tables": ["crm_deals"]}, 0.0),
        (
            [("execute-sql", {"query": "SELECT * FROM postgres.crm_deals"}, "1")],
            {"tables": [["postgres_crm_deals", "postgres.crm_deals"]]},
            1.0,
        ),
    ],
)
def test_sources_consulted_counts_successful_data_reads(
    calls: list[tuple], spec: dict[str, Any], expected_score: float
) -> None:
    score = SourcesConsulted()._run_eval_sync({"raw_log": _raw_tool_log(calls)}, {"sources_consulted": spec})

    assert score.score == expected_score


_V3_INSPECTION = ("execute-sql", {"query": "SELECT count() FROM crm_deals_v3"}, "0")


@pytest.mark.parametrize(
    "calls,scope,expected_score",
    [
        ([_V3_INSPECTION, _SQL_ANSWER], "answer", 1.0),
        ([_V3_INSPECTION, _SQL_ANSWER], None, 0.0),
        ([_SQL_ANSWER, _V3_INSPECTION], "answer", 0.0),
        ([_SQL_ANSWER], None, 1.0),
    ],
)
def test_sources_avoided_scopes_to_the_answer_query(
    calls: list[tuple], scope: str | None, expected_score: float
) -> None:
    spec: dict[str, Any] = {"tables": ["crm_deals_v3"]}
    if scope:
        spec["scope"] = scope

    score = SourcesAvoided()._run_eval_sync({"raw_log": _raw_tool_log(calls)}, {"sources_avoided": spec})

    assert score.score == expected_score


@pytest.mark.parametrize(
    "calls,expected_score",
    [
        ([("mcp__slack__search_messages", {"query": "tax"}, "ok")], 1.0),
        ([("mcp__slack__search_messages", {"query": "tax"}, "boom", "failed")], 0.0),
        ([("mcp__posthog__execute-sql", {"query": "SELECT 1"}, "1")], 0.0),
    ],
)
def test_server_used_requires_a_successful_call_on_that_server(calls: list[tuple], expected_score: float) -> None:
    score = ServerUsed()._run_eval_sync({"raw_log": _raw_tool_log(calls)}, {"server_used": {"server": "slack"}})

    assert score.score == expected_score
