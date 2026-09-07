from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.scorers import (
    FILE_EDIT_TOOLS,
    FLAG_LOOKUP_TOOLS,
    FlagStateUnchanged,
    ToolGroupDirection,
)


def _raw_tool_log(calls: Sequence[tuple[Any, ...]]) -> str:
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


def _score(calls: Sequence[tuple[Any, ...]], expected: dict | None, *, key: str = "should_edit"):
    return ToolGroupDirection(FILE_EDIT_TOOLS, name="code_edit_direction", key=key)._run_eval_sync(
        {"raw_log": _raw_tool_log(calls)},
        expected,
    )


@pytest.mark.parametrize(
    "calls,should_edit,expected_score",
    [
        ([("Edit", {"file_path": "/repo/a.py"}, "ok")], True, 1.0),
        ([("Edit", {"file_path": "/repo/a.py"}, "ok")], False, 0.0),
        ([("Read", {"file_path": "/repo/a.py"}, "ok")], False, 1.0),
        ([("Read", {"file_path": "/repo/a.py"}, "ok")], True, 0.0),
    ],
)
def test_tool_group_direction_scores_both_directions(
    calls: Sequence[tuple[Any, ...]], should_edit: bool, expected_score: float
) -> None:
    score = _score(calls, {"code_edit_direction": {"should_edit": should_edit}})

    assert score.score == expected_score


def test_tool_group_direction_ignores_a_failed_call() -> None:
    # A negative case must not flip because the agent tried an edit and the tool errored.
    score = _score(
        [("Write", {"file_path": "/repo/a.py"}, "boom", "failed")],
        {"code_edit_direction": {"should_edit": False}},
    )

    assert score.score == 1.0
    assert score.metadata["calls"] == []


@pytest.mark.parametrize(
    "expected",
    [None, {}, {"code_edit_direction": {}}, {"code_edit_direction": None}, {"other_scorer": {"should_edit": True}}],
)
def test_tool_group_direction_skips_when_the_case_declares_no_direction(expected: dict | None) -> None:
    # Presence of the key is the test, not its truthiness: a truthiness check here would
    # skip every should_edit=False case instead of grading it.
    score = _score([("Edit", {"file_path": "/repo/a.py"}, "ok")], expected)

    assert score.score is None


def test_tool_group_direction_grades_a_declared_false_direction() -> None:
    score = _score([("Edit", {"file_path": "/repo/a.py"}, "ok")], {"code_edit_direction": {"should_edit": False}})

    assert score.score == 0.0


def test_tool_group_direction_skips_without_a_log() -> None:
    score = ToolGroupDirection(FILE_EDIT_TOOLS, name="code_edit_direction", key="should_edit")._run_eval_sync(
        {}, {"code_edit_direction": {"should_edit": True}}
    )

    assert score.score is None


def test_flag_lookup_tools_match_mcp_names_the_parser_normalizes() -> None:
    # The agent calls these over MCP, so the log carries the mcp__posthog__ prefix.
    score = ToolGroupDirection(FLAG_LOOKUP_TOOLS, name="flag_lookup_direction", key="should_look_up")._run_eval_sync(
        {"raw_log": _raw_tool_log([("mcp__posthog__feature-flag-get-all", {"active": "STALE"}, "ok")])},
        {"flag_lookup_direction": {"should_look_up": True}},
    )

    assert score.score == 1.0
    assert score.metadata["calls"] == ["feature-flag-get-all"]


class TestFlagStateUnchanged(BaseTest):
    def _seeded_output(self) -> tuple[FeatureFlag, dict[str, Any]]:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="sunset-widget-rollout",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        state = {"key": flag.key, "active": True, "deleted": False, "archived": False, "filters": flag.filters}
        return flag, {"seed": {"flag_id": flag.id, "state": state}}

    def test_scores_an_untouched_flag_green(self) -> None:
        _, output = self._seeded_output()

        assert FlagStateUnchanged()._run_eval_sync(output).score == 1.0

    @parameterized.expand(
        [
            ("disabled", {"active": False}),
            ("archived", {"archived": True, "active": False}),
            # The soft-delete row must still be readable: reloading through the default
            # manager would raise DoesNotExist here instead of scoring the mutation.
            ("soft_deleted", {"deleted": True}),
        ]
    )
    def test_scores_a_mutated_flag_zero(self, _name: str, mutation: dict[str, Any]) -> None:
        flag, output = self._seeded_output()
        FeatureFlag.objects_including_soft_deleted.filter(pk=flag.pk).update(**mutation)

        score = FlagStateUnchanged()._run_eval_sync(output)

        assert score.score == 0.0
        assert set(score.metadata["changed_fields"]) == set(mutation)

    def test_scores_a_hard_deleted_flag_zero(self) -> None:
        flag, output = self._seeded_output()
        FeatureFlag.objects_including_soft_deleted.filter(pk=flag.pk).delete()

        assert FlagStateUnchanged()._run_eval_sync(output).score == 0.0

    def test_skips_a_case_that_seeded_no_flag(self) -> None:
        assert FlagStateUnchanged()._run_eval_sync({"seed": {}}).score is None
