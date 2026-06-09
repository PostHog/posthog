from __future__ import annotations

import json
from typing import Any

from ee.hogai.eval.sandboxed.error_tracking.scorers import (
    ERROR_TRACKING_WRITE_TOOLS,
    QUERY_ISSUE_EVENTS_TOOL,
    QUERY_ISSUES_LIST_TOOL,
    EventsToolUsed,
    IssueDrilldownOrder,
    IssuesListToolUsed,
    _recordings_text_has_results,
)


def _raw_tool_log(calls: list[tuple[str, dict[str, Any], object]]) -> str:
    lines = []
    for index, (name, raw_input, raw_output) in enumerate(calls, start=1):
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
                            "status": "completed",
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
