from __future__ import annotations

import json
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from posthog.test.base import BaseTest

from django.conf import settings

from parameterized import parameterized

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.scorers import (
    DEFINITION_READ_TOOLS,
    DEPENDENTS_READ_TOOLS,
    FILE_EDIT_TOOLS,
    FLAG_LOOKUP_TOOLS,
    FLAG_MUTATION_TOOLS,
    SCHEDULE_READ_TOOLS,
    FlagStateUnchanged,
    FreshReadsBeforeEdit,
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
    # tools.yaml may omit annotations (only GET and DELETE default), so read the generated
    # definitions, which hold the resolved values for every enabled tool.
    generated = json.loads(
        (Path(settings.BASE_DIR) / "services/mcp/schema/generated-tool-definitions.json").read_text()
    )
    return {name: spec for name, spec in generated.items() if spec["feature"] == "flags"}


def test_flag_mutation_tools_match_the_declared_write_surface() -> None:
    # FLAG_MUTATION_TOOLS is a literal so the guarded set stays a reviewed choice, but a
    # write verb added to tools.yaml must not slip past the suite silently. Bind the two.
    declared_write_verbs = {
        name for name, spec in _declared_tools().items() if spec["annotations"]["readOnlyHint"] is False
    }

    assert FLAG_MUTATION_TOOLS == declared_write_verbs


def test_read_tool_sets_name_enabled_read_only_tools() -> None:
    # The read sets are curated, not derived, so bind each name to the declared surface:
    # a renamed tool would otherwise be absorbed by the other names in its any-of group.
    # Hand-written tools (feature-flag-get-definition-by-key) live in the MCP server's
    # tool-definitions.json rather than in tools.yaml, so accept either home.
    tools = _declared_tools()
    hand_written = set(json.loads((Path(settings.BASE_DIR) / "services/mcp/schema/tool-definitions.json").read_text()))

    for name in sorted(FLAG_LOOKUP_TOOLS | DEFINITION_READ_TOOLS | DEPENDENTS_READ_TOOLS | SCHEDULE_READ_TOOLS):
        spec = tools.get(name)
        if spec is None:
            assert name in hand_written, name
            continue
        assert spec["annotations"]["readOnlyHint"] is True, name


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


# --- FreshReadsBeforeEdit ------------------------------------------------------------

_SEEDED_KEY = "sunset-widget-rollout"
_SEEDED_ID = 91001
# The shape the cleanup seeders return, which is what the scorer matches reads against.
_CLEANUP_SEED = {"flag_id": _SEEDED_ID, "flag_key": _SEEDED_KEY}

_DEFINITION_READ: tuple[Any, ...] = (
    "mcp__posthog__feature-flag-get-definition-by-key",
    {"key": _SEEDED_KEY},
    "ok",
)
_STATUS_READ: tuple[Any, ...] = ("mcp__posthog__feature-flags-status-retrieve", {"id": _SEEDED_ID}, "ok")
_DEPENDENTS_READ: tuple[Any, ...] = (
    "mcp__posthog__feature-flags-dependent-flags-retrieve",
    {"id": _SEEDED_ID},
    "ok",
)
_SCHEDULES_READ: tuple[Any, ...] = (
    "mcp__posthog__scheduled-changes-list",
    {"model_name": "FeatureFlag", "record_id": _SEEDED_ID},
    "ok",
)
# The four reads the skill repeats before the first edit, in the order it lists them.
_FOUR_READS: list[tuple[Any, ...]] = [_DEFINITION_READ, _STATUS_READ, _DEPENDENTS_READ, _SCHEDULES_READ]
_ASSESSMENT_READS: list[tuple[Any, ...]] = _FOUR_READS
_PRE_EDIT_READS: list[tuple[Any, ...]] = _FOUR_READS
# The "Find every repository reference" step searches for the flag's call sites, then the
# agent reads the file it is about to edit because the Edit tool refuses a file it has not
# read.
_REPOSITORY_SEARCH: list[tuple[Any, ...]] = [
    ("Grep", {"pattern": _SEEDED_KEY}, "src/widget.js:12"),
    ("Read", {"file_path": "/repo/src/widget.js"}, "ok"),
]
_FIRST_EDIT: tuple[Any, ...] = ("Edit", {"file_path": "/repo/src/widget.js"}, "ok")
_SECOND_EDIT: tuple[Any, ...] = ("Write", {"file_path": "/repo/src/other.js"}, "ok")
_OTHER_FLAG_READ: tuple[Any, ...] = (
    "mcp__posthog__feature-flag-get-definition-by-key",
    {"key": "some-other-flag"},
    "ok",
)


def _fresh_read_score(calls: Sequence[tuple[Any, ...]], expected: dict | None):
    return FreshReadsBeforeEdit()._run_eval_sync({"raw_log": _raw_tool_log(calls), "seed": _CLEANUP_SEED}, expected)


class TestFreshReadsBeforeEdit:
    _REQUIRED = {"fresh_reads_before_edit": {"required": True}}

    def test_flags_an_edit_that_never_repeated_the_reads(self) -> None:
        score = _fresh_read_score([*_ASSESSMENT_READS, *_REPOSITORY_SEARCH, _FIRST_EDIT], self._REQUIRED)

        assert score.score == 0.0
        assert score.metadata["groups_missing"] == ["definition", "dependents", "schedules", "status"]

    def test_flags_a_run_that_repeated_only_the_definition(self) -> None:
        # A new schedule or dependent flag does not change the definition, so re-reading the
        # definition alone leaves exactly the change the step exists to catch undetected.
        score = _fresh_read_score(
            [*_ASSESSMENT_READS, *_REPOSITORY_SEARCH, _DEFINITION_READ, _FIRST_EDIT],
            self._REQUIRED,
        )

        assert score.score == 0.0
        assert score.metadata["groups_read"] == ["definition"]
        assert score.metadata["groups_missing"] == ["dependents", "schedules", "status"]

    def test_flags_two_assessment_rounds_followed_by_an_edit(self) -> None:
        # Both rounds land while assessing, so neither one is the pre-edit repeat the
        # "Apply the retained path" step asks for. Counting reads before the edit would pass
        # this run.
        score = _fresh_read_score(
            [*_ASSESSMENT_READS, *_ASSESSMENT_READS, *_REPOSITORY_SEARCH, _FIRST_EDIT],
            self._REQUIRED,
        )

        assert score.score == 0.0

    def test_flags_a_search_that_ran_before_the_assessment_reads(self) -> None:
        # The skill's "Establish scope" step searches the repository for the key before any
        # definition is read. Taking the first search in the run as the divider would score
        # the assessment reads as the repeat.
        score = _fresh_read_score(
            [_REPOSITORY_SEARCH[0], *_ASSESSMENT_READS, *_REPOSITORY_SEARCH, _FIRST_EDIT],
            self._REQUIRED,
        )

        assert score.score == 0.0

    def test_a_search_between_assessment_and_the_repeat_does_not_open_the_window_early(self) -> None:
        # The existing-work step searches before the retained path, which moves the divider
        # earlier. Requiring all four groups is what keeps that harmless.
        score = _fresh_read_score(
            [
                *_ASSESSMENT_READS,
                ("Grep", {"pattern": _SEEDED_KEY}, "src/widget.js:12"),
                _DEFINITION_READ,
                *_REPOSITORY_SEARCH,
                _FIRST_EDIT,
            ],
            self._REQUIRED,
        )

        assert score.score == 0.0
        assert score.metadata["groups_read"] == ["definition"]

    def test_a_read_of_another_flag_does_not_count(self) -> None:
        # Without the seed match, any flag's definition read between the search and the edit
        # would satisfy the definition group, including one that never looked at the flag
        # under cleanup.
        score = _fresh_read_score(
            [
                *_ASSESSMENT_READS,
                *_REPOSITORY_SEARCH,
                _OTHER_FLAG_READ,
                _STATUS_READ,
                _DEPENDENTS_READ,
                _SCHEDULES_READ,
                _FIRST_EDIT,
            ],
            self._REQUIRED,
        )

        assert score.score == 0.0
        assert score.metadata["groups_missing"] == ["definition"]

    def test_flags_a_first_edit_made_against_the_assessment_reads(self) -> None:
        # The repeat arrives between the two edits, so the first file was edited against the
        # assessment reads. Measuring from the last edit instead would pass this run.
        score = _fresh_read_score(
            [*_ASSESSMENT_READS, *_REPOSITORY_SEARCH, _FIRST_EDIT, *_PRE_EDIT_READS, _SECOND_EDIT],
            self._REQUIRED,
        )

        assert score.score == 0.0

    def test_passes_all_four_reads_between_the_search_and_the_edit(self) -> None:
        score = _fresh_read_score(
            [*_ASSESSMENT_READS, *_REPOSITORY_SEARCH, *_PRE_EDIT_READS, _FIRST_EDIT],
            self._REQUIRED,
        )

        assert score.score == 1.0
        assert score.metadata["groups_read"] == ["definition", "dependents", "schedules", "status"]

    def test_reads_after_the_edit_do_not_count(self) -> None:
        score = _fresh_read_score(
            [*_ASSESSMENT_READS, *_REPOSITORY_SEARCH, _FIRST_EDIT, *_PRE_EDIT_READS],
            self._REQUIRED,
        )

        assert score.score == 0.0

    def test_a_failed_repeat_does_not_count(self) -> None:
        # A failed attempt gives no assurance a real read landed.
        failed_definition_read = (*_DEFINITION_READ[:2], "boom", "failed")
        score = _fresh_read_score(
            [
                *_ASSESSMENT_READS,
                *_REPOSITORY_SEARCH,
                failed_definition_read,
                _STATUS_READ,
                _DEPENDENTS_READ,
                _SCHEDULES_READ,
                _FIRST_EDIT,
            ],
            self._REQUIRED,
        )

        assert score.score == 0.0
        assert score.metadata["groups_missing"] == ["definition"]

    def test_flags_an_edit_with_no_repository_search_at_all(self) -> None:
        # Nothing divides assessment from the edit, so no read can be shown to be a repeat.
        score = _fresh_read_score([*_ASSESSMENT_READS, *_PRE_EDIT_READS, _FIRST_EDIT], self._REQUIRED)

        assert score.score == 0.0

    def test_flags_an_edit_that_never_read_the_definition(self) -> None:
        score = _fresh_read_score([*_REPOSITORY_SEARCH, _FIRST_EDIT], self._REQUIRED)

        assert score.score == 0.0
        assert score.metadata["reason"] == "The agent edited without reading the flag definition first"

    def test_skips_a_case_that_never_edited(self) -> None:
        score = _fresh_read_score([*_ASSESSMENT_READS, *_REPOSITORY_SEARCH], self._REQUIRED)

        assert score.score is None

    def test_skips_when_the_only_edit_failed(self) -> None:
        # A failed edit attempt left nothing on disk to gate, the same as not editing.
        failed_edit = (*_FIRST_EDIT[:2], "boom", "failed")
        score = _fresh_read_score([*_ASSESSMENT_READS, *_REPOSITORY_SEARCH, failed_edit], self._REQUIRED)

        assert score.score is None

    @pytest.mark.parametrize("expected", [None, {}, {"fresh_reads_before_edit": {}}])
    def test_skips_when_the_case_declares_no_requirement(self, expected: dict | None) -> None:
        score = _fresh_read_score(
            [*_ASSESSMENT_READS, *_REPOSITORY_SEARCH, *_PRE_EDIT_READS, _FIRST_EDIT],
            expected,
        )

        assert score.score is None
