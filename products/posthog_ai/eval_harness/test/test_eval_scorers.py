from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from products.posthog_ai.eval_harness.log_parser import SKILL_TOOL_NAME
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
