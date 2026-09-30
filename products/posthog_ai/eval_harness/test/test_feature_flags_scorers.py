from __future__ import annotations

import json
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from posthog.test.base import BaseTest

from django.conf import settings

import yaml
from parameterized import parameterized

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.scorers import (
    DEPENDENTS_READ_TOOLS,
    FILE_EDIT_TOOLS,
    FLAG_LOOKUP_TOOLS,
    FLAG_MUTATION_TOOLS,
    SCHEDULE_READ_TOOLS,
    FlagStateUnchanged,
    ToolGroupDirection,
    read_flag_state,
)
from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log


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


def test_tool_group_direction_skips_without_a_log() -> None:
    score = ToolGroupDirection(FILE_EDIT_TOOLS, name="code_edit_direction", key="should_edit")._run_eval_sync(
        {}, {"code_edit_direction": {"should_edit": True}}
    )

    assert score.score is None


@pytest.mark.parametrize("tool", sorted(FLAG_LOOKUP_TOOLS))
def test_flag_lookup_tools_match_mcp_names_the_parser_normalizes(tool: str) -> None:
    # The agent calls these over MCP, so the log carries the mcp__posthog__ prefix.
    score = ToolGroupDirection(FLAG_LOOKUP_TOOLS, name="flag_lookup_direction", key="should_look_up")._run_eval_sync(
        {"raw_log": _raw_tool_log([(f"mcp__posthog__{tool}", {}, "ok")])},
        {"flag_lookup_direction": {"should_look_up": True}},
    )

    assert score.score == 1.0
    assert score.metadata["calls"] == [tool]


def _declared_tools() -> dict[str, Any]:
    tools_yaml = Path(settings.BASE_DIR) / "products/feature_flags/mcp/tools.yaml"
    return yaml.safe_load(tools_yaml.read_text())["tools"]


def test_flag_mutation_tools_match_the_declared_write_surface() -> None:
    # FLAG_MUTATION_TOOLS is a literal so the guarded set stays a reviewed choice, but a
    # write verb added to tools.yaml must not slip past the suite silently. Bind the two.
    declared_write_verbs = {
        name
        for name, spec in _declared_tools().items()
        if spec.get("enabled") and spec.get("annotations", {}).get("readOnly") is False
    }

    assert FLAG_MUTATION_TOOLS == declared_write_verbs


def test_read_tool_sets_name_enabled_read_only_tools() -> None:
    # The read sets are curated, not derived, so bind each name to the declared surface:
    # a renamed tool would otherwise be absorbed by the other names in its any-of group.
    # Hand-written tools (feature-flag-get-definition-by-key) live in the MCP server's
    # tool-definitions.json rather than in tools.yaml, so accept either home.
    tools = _declared_tools()
    hand_written = set(json.loads((Path(settings.BASE_DIR) / "services/mcp/schema/tool-definitions.json").read_text()))

    for name in sorted(FLAG_LOOKUP_TOOLS | DEPENDENTS_READ_TOOLS | SCHEDULE_READ_TOOLS):
        spec = tools.get(name)
        if spec is None:
            assert name in hand_written, name
            continue
        assert spec.get("enabled") and spec.get("annotations", {}).get("readOnly") is True, name


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

    @staticmethod
    def _score_via_db(output: dict[str, Any]) -> Any:
        # Read on the main thread, then score: `eval_async`'s to_thread read opens a
        # second DB connection that cannot see this test's uncommitted transaction.
        seed = output["seed"]
        return FlagStateUnchanged()._score_state(seed["state"], read_flag_state(seed["flag_id"]))

    def test_scores_an_untouched_flag_green(self) -> None:
        _, output = self._seeded_output()

        assert self._score_via_db(output).score == 1.0

    @parameterized.expand(
        [
            ("disabled", {"active": False}),
            ("archived", {"archived": True, "active": False}),
            # The soft-delete row must still be readable: reading through the default
            # manager would return None here instead of scoring the mutation.
            ("soft_deleted", {"deleted": True}),
        ]
    )
    def test_scores_a_mutated_flag_zero(self, _name: str, mutation: dict[str, Any]) -> None:
        flag, output = self._seeded_output()
        FeatureFlag.objects_including_soft_deleted.filter(pk=flag.pk).update(**mutation)

        score = self._score_via_db(output)

        assert score.score == 0.0
        assert set(score.metadata["changed_fields"]) == set(mutation)

    def test_scores_a_hard_deleted_flag_zero(self) -> None:
        flag, output = self._seeded_output()
        FeatureFlag.objects_including_soft_deleted.filter(pk=flag.pk).delete()

        assert self._score_via_db(output).score == 0.0

    def test_skips_a_case_that_seeded_no_flag(self) -> None:
        assert asyncio.run(FlagStateUnchanged().eval_async({"seed": {}})).score is None

    def test_eval_async_reads_the_row_off_the_event_loop(self) -> None:
        # The harness awaits scorers on the event loop, where a sync ORM call raises
        # SynchronousOnlyOperation. This drives the real async path; the to_thread
        # connection cannot see this test's transaction, so the row reads as gone —
        # the assertion is that it scored instead of raising.
        _, output = self._seeded_output()

        score = asyncio.run(FlagStateUnchanged().eval_async(output))

        assert score.score is not None
