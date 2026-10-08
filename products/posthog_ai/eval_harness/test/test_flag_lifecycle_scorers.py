from __future__ import annotations

import json
from typing import Any

from parameterized import parameterized

from products.feature_flags.evals.eval_flag_answers import flag_write_tools
from products.feature_flags.evals.scorers import (
    AttemptedTool,
    AvoidedTool,
    CalledExpectedTool,
    CreatedFlagWithTags,
    FinalMessageJudge,
    FinalMessageNames,
    GenericUpdateOmitsFields,
    GenericUpdateSetsFields,
    PreservedUnrelatedConfig,
    UpdatedRolloutTo,
)
from products.feature_flags.evals.seeders import (
    DEPENDENT_FLAG_KEY,
    ROLLOUT_FROM_PERCENTAGE,
    ROLLOUT_INITIAL_FILTERS,
    ROLLOUT_PINNED_PERCENTAGE,
    ROLLOUT_TO_PERCENTAGE,
)
from products.posthog_ai.eval_harness.scorers.contract import Score

CREATE_TOOL = "create-feature-flag"
UPDATE_TOOL = "update-feature-flag"
BY_KEY_TOOL = "feature-flag-get-definition-by-key"


def _session_update(sequence: int, update: dict) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": f"2026-07-16T10:00:{sequence:02d}.000Z",
            "notification": {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": "session", "update": update},
            },
        }
    )


def _tool_log(calls: list[tuple[str, dict[str, Any], str]]) -> str:
    updates: list[str] = []
    sequence = 0
    for index, (tool_name, raw_input, status) in enumerate(calls, start=1):
        call_id = f"call-{index}"
        sequence += 1
        updates.append(
            _session_update(
                sequence,
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": call_id,
                    "status": "pending",
                    "rawInput": raw_input,
                    "title": tool_name,
                    "_meta": {"claudeCode": {"toolName": tool_name}},
                },
            )
        )
        sequence += 1
        updates.append(
            _session_update(
                sequence,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": call_id,
                    "status": status,
                    "rawOutput": "error" if status == "failed" else "ok",
                },
            )
        )
    return "\n".join(updates)


SEEDED_FILTERS: dict[str, Any] = ROLLOUT_INITIAL_FILTERS

ROLLOUT_SEED = {
    "initial_filters": SEEDED_FILTERS,
    "rollout_from_percentage": ROLLOUT_FROM_PERCENTAGE,
    "rollout_to_percentage": ROLLOUT_TO_PERCENTAGE,
}

SEEDED_FLAG_ID = 7
SEEDED_FLAG_KEY = "smart-upload-retry"
FLAG_SEED = {"feature_flag_id": SEEDED_FLAG_ID, "feature_flag_key": SEEDED_FLAG_KEY}

RENAMED_KEY = "file-preview-tiles"
NEW_DESCRIPTION = "Show grid thumbnails in the file browser"

# What `seed_rollout_flag` really returns: the rollout percentages plus the flag's identity.
ROLLOUT_SEED_WITH_IDENTITY = {**ROLLOUT_SEED, **FLAG_SEED}


def _merged_filters() -> dict[str, Any]:
    merged = json.loads(json.dumps(SEEDED_FILTERS))
    merged["groups"][1]["rollout_percentage"] = ROLLOUT_TO_PERCENTAGE
    return merged


def _reordered_filters() -> dict[str, Any]:
    filters = _merged_filters()
    filters["groups"].reverse()
    for group in filters["groups"]:
        group["properties"] = [dict(reversed(list(prop.items()))) for prop in group["properties"]]
    return filters


def _flattened_filters() -> dict[str, Any]:
    """The modal bad write: the new percentage, and nothing else the flag carried."""
    return {"groups": [{"properties": [], "rollout_percentage": ROLLOUT_TO_PERCENTAGE}]}


def _without(key: str) -> dict[str, Any]:
    filters = _merged_filters()
    filters.pop(key)
    return filters


def _swapped_filters() -> dict[str, Any]:
    """The two release conditions trade percentages, so the catch-all goes to 100%."""
    filters = _merged_filters()
    filters["groups"][0]["rollout_percentage"] = ROLLOUT_TO_PERCENTAGE
    filters["groups"][1]["rollout_percentage"] = ROLLOUT_PINNED_PERCENTAGE
    return filters


def _unnamed_variants() -> dict[str, Any]:
    filters = _merged_filters()
    for variant in filters["multivariate"]["variants"]:
        variant.pop("name")
    return filters


def _group_level_variant_override() -> dict[str, Any]:
    """The merged write, plus an override pinning the moved condition to one variant."""
    filters = _merged_filters()
    filters["groups"][1]["variant"] = "retry"
    return filters


# A spec-driven scorer that returned 0.0 instead of None on a case it does not apply to
# would drag every unrelated case down, so the suite mean would stop meaning anything.
@parameterized.expand(
    [
        (CalledExpectedTool(), "called_expected_tool"),
        (AttemptedTool(), "attempted_tool"),
        (AvoidedTool(), "avoided_tool"),
        (GenericUpdateOmitsFields(), "generic_update_omits_fields"),
        (GenericUpdateSetsFields(), "generic_update_sets_fields"),
        (CreatedFlagWithTags(), "created_flag_with_tags"),
        (PreservedUnrelatedConfig(), "preserved_unrelated_config"),
    ]
)
def test_flag_scorers_self_skip_when_the_case_carries_no_spec(scorer: Any, scorer_name: str) -> None:
    score = scorer._run_eval_sync({"raw_log": _tool_log([])}, {})

    assert score.name == scorer_name
    assert score.score is None


# The read-only case expects the agent to try the write and be refused, so a failed call
# has to pass. Counting a refused call as landed would fail every correct run of that case,
# and counting a completed one as avoided would pass a run where the write got through.
@parameterized.expand(
    [
        ("read_only_work_only", [("feature-flags-status-retrieve", {"id": "7"}, "completed")], 1.0),
        ("attempted_and_refused", [("feature-flag-disable", {"id": "7"}, "failed")], 1.0),
        ("write_landed", [("feature-flag-disable", {"id": "7"}, "completed")], 0.0),
        ("landed_a_different_forbidden_tool", [(UPDATE_TOOL, {"id": "7", "active": False}, "completed")], 0.0),
    ]
)
def test_avoided_tool(_name: str, calls: list[tuple[str, dict[str, Any], str]], expected_score: float) -> None:
    score = AvoidedTool()._run_eval_sync(
        {"raw_log": _tool_log(calls)},
        {"avoided_tool": {"tools": ["feature-flag-disable", UPDATE_TOOL]}},
    )

    assert score.score == expected_score


# The refusal case turns the rule above around. Its other rows all pass on a run that made
# no calls at all, so a message claiming "I do not have permission" scores full marks
# without the agent ever meeting the restriction. A refused attempt is the evidence.
@parameterized.expand(
    [
        ("attempted_and_was_refused", [("feature-flag-disable", {"id": SEEDED_FLAG_ID}, "failed")], 1.0),
        # Whether the write landed is the avoided-tool row's question, not this one's.
        ("attempt_landed", [("feature-flag-disable", {"id": SEEDED_FLAG_ID}, "completed")], 1.0),
        ("read_the_flag_and_stopped", [(BY_KEY_TOOL, {"key": SEEDED_FLAG_KEY}, "completed")], 0.0),
        ("tried_on_another_flag", [("feature-flag-disable", {"id": 4242}, "failed")], 0.0),
    ]
)
def test_attempted_tool(_name: str, calls: list[tuple[str, dict[str, Any], str]], expected_score: float) -> None:
    score = AttemptedTool()._run_eval_sync(
        {"raw_log": _tool_log(calls), "seed": FLAG_SEED},
        {"attempted_tool": {"tools": ["feature-flag-disable", UPDATE_TOOL]}},
    )

    assert score.score == expected_score


# The mirror of the rule above: only a successful call counts as having reached for the tool.
@parameterized.expand(
    [
        ("called_it", [("feature-flag-disable", {"id": "7"}, "completed")], 1.0),
        ("called_one_of_several", [(UPDATE_TOOL, {"id": "7"}, "completed")], 1.0),
        ("attempt_failed", [("feature-flag-disable", {"id": "7"}, "failed")], 0.0),
        ("reached_for_something_else", [("feature-flag-archive", {"id": "7"}, "completed")], 0.0),
    ]
)
def test_called_expected_tool(_name: str, calls: list[tuple[str, dict[str, Any], str]], expected_score: float) -> None:
    score = CalledExpectedTool()._run_eval_sync(
        {"raw_log": _tool_log(calls)},
        {"called_expected_tool": {"tools": ["feature-flag-disable", UPDATE_TOOL]}},
    )

    assert score.score == expected_score


# Every case runs in a team that already holds the demo project's own flags, so the right
# tool on the wrong flag is the mis-resolution these cases exist to catch. The id arrives
# as a string or a number depending on how the agent wrote the call, and a rename carries
# the new key alongside the seeded id.
@parameterized.expand(
    [
        ("lifecycle_call_on_the_seeded_flag", [("feature-flag-disable", {"id": SEEDED_FLAG_ID}, "completed")], 1.0),
        ("id_written_as_a_string", [("feature-flag-disable", {"id": str(SEEDED_FLAG_ID)}, "completed")], 1.0),
        ("lifecycle_call_on_another_flag", [("feature-flag-disable", {"id": 4242}, "completed")], 0.0),
        (
            "rename_keeps_the_seeded_id_and_takes_a_new_key",
            [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "key": "renamed"}, "completed")],
            1.0,
        ),
        ("lookup_of_the_seeded_key", [(BY_KEY_TOOL, {"key": SEEDED_FLAG_KEY}, "completed")], 1.0),
        ("lookup_under_an_accepted_alias", [(BY_KEY_TOOL, {"flag_key": SEEDED_FLAG_KEY}, "completed")], 1.0),
        ("lookup_of_another_key", [(BY_KEY_TOOL, {"key": "file-previews"}, "completed")], 0.0),
        # A search names no single flag, so it is graded on the tool alone.
        ("search_names_no_flag", [("feature-flag-get-all", {"search": "upload"}, "completed")], 1.0),
    ]
)
def test_called_expected_tool_grades_the_seeded_flag(
    _name: str, calls: list[tuple[str, dict[str, Any], str]], expected_score: float
) -> None:
    score = CalledExpectedTool()._run_eval_sync(
        {"raw_log": _tool_log(calls), "seed": FLAG_SEED},
        {"called_expected_tool": {"tools": ["feature-flag-disable", UPDATE_TOOL, BY_KEY_TOOL, "feature-flag-get-all"]}},
    )

    assert score.score == expected_score


# Four judges are registered across the two suites and each case opts in to some of them.
# If the spec check stopped short-circuiting, every case would be graded by questions
# written about a different case. `FinalMessageJudge` deliberately scores a missing final
# message 0.0 rather than None, because a run that said nothing did not answer the user.
@parameterized.expand(
    [
        ("case_did_not_opt_in", "anything", {}, None),
        ("run_left_no_final_message", "", {"refused_without_blaming": {"required": True}}, 0.0),
    ]
)
def test_final_message_judge_short_circuits(
    _name: str, last_message: str, expected: dict[str, Any], expected_score: float | None
) -> None:
    prepared = FinalMessageJudge(name="refused_without_blaming", question="q")._prepare(
        {"last_message": last_message}, expected
    )

    assert isinstance(prepared, Score)
    assert prepared.score == expected_score


@parameterized.expand(
    [
        ("metadata_only_edit", [(UPDATE_TOOL, {"id": "7", "key": "renamed"}, "completed")], ["filters"], 1.0),
        (
            "edit_replaced_targeting",
            [(UPDATE_TOOL, {"id": "7", "key": "renamed", "filters": {"groups": []}}, "completed")],
            ["filters"],
            0.0,
        ),
        # A rejected write changed nothing, so it is not the failure this grades.
        (
            "rejected_edit_sent_targeting",
            [(UPDATE_TOOL, {"id": "7", "filters": {"groups": []}}, "failed")],
            ["filters"],
            1.0,
        ),
        (
            "state_flip_through_generic_update",
            [(UPDATE_TOOL, {"id": "7", "active": False}, "completed")],
            ["active", "archived"],
            0.0,
        ),
        ("state_flip_through_lifecycle_tool", [("feature-flag-disable", {"id": "7"}, "completed")], ["active"], 1.0),
    ]
)
def test_generic_update_omits_fields(
    _name: str, calls: list[tuple[str, dict[str, Any], str]], fields: list[str], expected_score: float
) -> None:
    scorer = GenericUpdateOmitsFields()
    score = scorer._run_eval_sync({"raw_log": _tool_log(calls)}, {"generic_update_omits_fields": {"fields": fields}})

    assert score.score == expected_score


# `name` holds the description on this model, so the rename and the redescribe land in two
# different fields. The neighbouring omits-fields check passes on a body carrying nothing at
# all, which is why the positive half exists.
@parameterized.expand(
    [
        (
            "wrote_both_halves",
            [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "key": RENAMED_KEY, "name": NEW_DESCRIPTION}, "completed")],
            1.0,
        ),
        ("update_carried_nothing", [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID}, "completed")], 0.0),
        # The agent heard "rename" and wrote the new key into the description field.
        (
            "wrote_the_key_into_the_description",
            [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "name": RENAMED_KEY}, "completed")],
            0.0,
        ),
        (
            "renamed_but_left_the_description",
            [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "key": RENAMED_KEY}, "completed")],
            0.0,
        ),
        (
            "wrote_a_description_of_its_own",
            [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "key": RENAMED_KEY, "name": "Thumbnails"}, "completed")],
            0.0,
        ),
        # Two calls is chatty, not wrong, so the fields may arrive separately.
        (
            "split_the_edit_across_two_updates",
            [
                (UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "key": RENAMED_KEY}, "completed"),
                (UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "name": NEW_DESCRIPTION}, "completed"),
            ],
            1.0,
        ),
        (
            "case_and_spacing_are_the_agents_to_choose",
            [
                (
                    UPDATE_TOOL,
                    {"id": SEEDED_FLAG_ID, "key": RENAMED_KEY, "name": f"  {NEW_DESCRIPTION.upper()} "},
                    "completed",
                )
            ],
            1.0,
        ),
        (
            "rejected_update_changed_nothing",
            [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "key": RENAMED_KEY, "name": NEW_DESCRIPTION}, "failed")],
            0.0,
        ),
        (
            "edited_another_flag",
            [(UPDATE_TOOL, {"id": 4242, "key": RENAMED_KEY, "name": NEW_DESCRIPTION}, "completed")],
            0.0,
        ),
    ]
)
def test_generic_update_sets_fields(
    _name: str, calls: list[tuple[str, dict[str, Any], str]], expected_score: float
) -> None:
    score = GenericUpdateSetsFields()._run_eval_sync(
        {"raw_log": _tool_log(calls), "seed": FLAG_SEED},
        {"generic_update_sets_fields": {"fields": {"key": RENAMED_KEY, "name": NEW_DESCRIPTION}}},
    )

    assert score.score == expected_score


@parameterized.expand(
    [
        ("tagged_first_try", [(CREATE_TOOL, {"key": "k", "tags": ["billing"]}, "completed")], 1.0),
        ("no_tags", [(CREATE_TOOL, {"key": "k"}, "completed")], 0.0),
        ("blank_tag", [(CREATE_TOOL, {"key": "k", "tags": ["  "]}, "completed")], 0.0),
        # The recovery path the required-tags case is built to measure: rejected without
        # a tag, then created with one.
        (
            "recovered_after_rejection",
            [
                (CREATE_TOOL, {"key": "k"}, "failed"),
                (CREATE_TOOL, {"key": "k", "tags": ["billing"]}, "completed"),
            ],
            1.0,
        ),
        ("never_landed", [(CREATE_TOOL, {"key": "k", "tags": ["billing"]}, "failed")], 0.0),
    ]
)
def test_created_flag_with_tags(
    _name: str, calls: list[tuple[str, dict[str, Any], str]], expected_score: float
) -> None:
    scorer = CreatedFlagWithTags()
    score = scorer._run_eval_sync({"raw_log": _tool_log(calls)}, {"created_flag_with_tags": {"required": True}})

    assert score.score == expected_score


# The case asks for one flag, so a tagged create under some other key is a different flag
# and leaves the asked-for one unmade.
@parameterized.expand(
    [
        ("created_the_flag_the_case_asked_for", "billing-sync-killswitch", 1.0),
        ("created_a_different_flag", "some-other-flag", 0.0),
    ]
)
def test_created_flag_with_tags_grades_the_asked_for_key(_name: str, created_key: str, expected_score: float) -> None:
    scorer = CreatedFlagWithTags()
    score = scorer._run_eval_sync(
        {
            "raw_log": _tool_log([(CREATE_TOOL, {"key": created_key, "tags": ["billing"]}, "completed")]),
            "seed": {"feature_flag_key": "billing-sync-killswitch", "requires_tags": True},
        },
        {"created_flag_with_tags": {"required": True}},
    )

    assert score.score == expected_score


@parameterized.expand(
    [
        ("merged_the_current_definition", _merged_filters(), 1.0),
        # An agent that rewrites the definition may reorder keys and conditions without
        # changing who the flag serves. Failing that would fail every correct run.
        ("rewrote_the_definition_in_a_different_order", _reordered_filters(), 1.0),
        ("dropped_the_variants", _without("multivariate"), 0.0),
        ("dropped_the_payloads", _without("payloads"), 0.0),
        (
            "dropped_the_other_release_condition",
            {"groups": [{"properties": [], "rollout_percentage": ROLLOUT_TO_PERCENTAGE}]},
            0.0,
        ),
        (
            "kept_the_condition_count_but_lost_its_properties",
            {
                "groups": [
                    {"properties": [], "rollout_percentage": ROLLOUT_PINNED_PERCENTAGE},
                    {"properties": [], "rollout_percentage": ROLLOUT_TO_PERCENTAGE},
                ],
                "multivariate": SEEDED_FILTERS["multivariate"],
                "payloads": SEEDED_FILTERS["payloads"],
            },
            0.0,
        ),
        ("never_moved_the_target_group", SEEDED_FILTERS, 0.0),
        # The same two percentages come back, on the wrong conditions: everyone now gets
        # the flag and only paying customers are sampled. Comparing the percentages apart
        # from the conditions they serve cannot see it.
        ("swapped_the_targeting_between_the_conditions", _swapped_filters(), 0.0),
        # Both names are user-facing, and a variant checked by its percentage keeps them
        # only by accident.
        ("dropped_the_variant_names", _unnamed_variants(), 0.0),
        # Everything the seed declared is still there, plus a group-level override that
        # pins the whole condition to one variant.
        ("added_a_group_level_variant_override", _group_level_variant_override(), 0.0),
    ]
)
def test_preserved_unrelated_config(_name: str, written: dict[str, Any], expected_score: float) -> None:
    scorer = PreservedUnrelatedConfig()
    score = scorer._run_eval_sync(
        {
            "raw_log": _tool_log([(UPDATE_TOOL, {"id": "7", "filters": written}, "completed")]),
            "seed": ROLLOUT_SEED,
        },
        {"preserved_unrelated_config": {"required": True}},
    )

    assert score.score == expected_score


# `filters` replaces the whole object, so a write that flattened it lost whatever a
# teammate added since the agent's read, and the flag serves the wrong people until the
# next write lands. Grading the last write only would call that run clean.
@parameterized.expand(
    [
        ("merged_on_the_first_attempt", [_merged_filters()], 1.0),
        ("flattened_then_repaired", [_flattened_filters(), _merged_filters()], 0.0),
        ("repeated_the_correct_write", [_merged_filters(), _merged_filters()], 1.0),
    ]
)
def test_preserved_unrelated_config_grades_every_write(
    _name: str, written: list[dict[str, Any]], expected_score: float
) -> None:
    scorer = PreservedUnrelatedConfig()
    score = scorer._run_eval_sync(
        {
            "raw_log": _tool_log(
                [(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "filters": filters}, "completed") for filters in written]
            ),
            "seed": ROLLOUT_SEED_WITH_IDENTITY,
        },
        {"preserved_unrelated_config": {"required": True}},
    )

    assert score.score == expected_score


# Another flag's filters compared against this seed would fail nearly every check, so the
# write has to be attributed before it is graded — and a run that only ever wrote to
# another flag has not made the edit at all.
@parameterized.expand(
    [
        ("another_flags_write_is_not_graded", [(4242, _flattened_filters()), (SEEDED_FLAG_ID, _merged_filters())], 1.0),
        ("only_ever_wrote_to_another_flag", [(4242, _merged_filters())], 0.0),
    ]
)
def test_preserved_unrelated_config_grades_the_seeded_flag(
    _name: str, written: list[tuple[int, dict[str, Any]]], expected_score: float
) -> None:
    scorer = PreservedUnrelatedConfig()
    score = scorer._run_eval_sync(
        {
            "raw_log": _tool_log(
                [(UPDATE_TOOL, {"id": flag_id, "filters": filters}, "completed") for flag_id, filters in written]
            ),
            "seed": ROLLOUT_SEED_WITH_IDENTITY,
        },
        {"preserved_unrelated_config": {"required": True}},
    )

    assert score.score == expected_score


def test_preserved_unrelated_config_fails_when_no_update_sent_filters() -> None:
    scorer = PreservedUnrelatedConfig()
    score = scorer._run_eval_sync(
        {
            "raw_log": _tool_log([("feature-flag-enable", {"id": "7"}, "completed")]),
            "seed": ROLLOUT_SEED,
        },
        {"preserved_unrelated_config": {"required": True}},
    )

    assert score.score == 0.0


# The stale case's judge accepts several caveats, so it cannot say which one the agent
# found. This row is the one that requires the blocking dependent flag by name.
@parameterized.expand(
    [
        ("named_it", f"It is stale, but {DEPENDENT_FLAG_KEY} depends on it.", 1.0),
        ("named_it_in_other_case", f"Blocked by {DEPENDENT_FLAG_KEY.upper()}.", 1.0),
        ("offered_a_different_caveat", "It is stale. Check for code references first.", 0.0),
        ("said_nothing", "", 0.0),
    ]
)
def test_final_message_names(_name: str, last_message: str, expected_score: float) -> None:
    score = FinalMessageNames()._run_eval_sync(
        {"last_message": last_message},
        {"final_message_names": {"text": [DEPENDENT_FLAG_KEY]}},
    )

    assert score.score == expected_score


# The key-reuse judge reads the final message, so "I reused the existing flag" scores the
# same whether or not the update happened. This is the row that reads the tool calls.
@parameterized.expand(
    [
        ("set_the_asked_for_rollout", [(SEEDED_FLAG_ID, 30)], 1.0),
        ("wrote_a_different_rollout", [(SEEDED_FLAG_ID, 50)], 0.0),
        ("claimed_it_without_writing", [], 0.0),
        ("wrote_it_on_another_flag", [(4242, 30)], 0.0),
        ("reached_it_on_a_later_write", [(SEEDED_FLAG_ID, 50), (SEEDED_FLAG_ID, 30)], 1.0),
    ]
)
def test_updated_rollout_to(_name: str, written: list[tuple[int, int]], expected_score: float) -> None:
    score = UpdatedRolloutTo()._run_eval_sync(
        {
            "raw_log": _tool_log(
                [
                    (UPDATE_TOOL, {"id": flag_id, "filters": {"groups": [{"rollout_percentage": pct}]}}, "completed")
                    for flag_id, pct in written
                ]
                or [("feature-flag-get-definition-by-key", {"key": SEEDED_FLAG_KEY}, "completed")]
            ),
            "seed": FLAG_SEED,
        },
        {"updated_rollout_to": {"percentage": 30}},
    )

    assert score.score == expected_score


# A seed missing either percentage makes every condition read as pinned, so a correct
# write fails and the metadata blames the agent. The guard names the seed instead.
@parameterized.expand(
    [
        ("no_from_percentage", "rollout_from_percentage"),
        ("no_to_percentage", "rollout_to_percentage"),
    ]
)
def test_preserved_unrelated_config_names_a_seed_missing_its_percentages(_name: str, dropped: str) -> None:
    seed = {key: value for key, value in ROLLOUT_SEED_WITH_IDENTITY.items() if key != dropped}
    score = PreservedUnrelatedConfig()._run_eval_sync(
        {
            "raw_log": _tool_log([(UPDATE_TOOL, {"id": SEEDED_FLAG_ID, "filters": _merged_filters()}, "completed")]),
            "seed": seed,
        },
        {"preserved_unrelated_config": {"required": True}},
    )

    assert score.score == 0.0
    assert score.metadata["missing"] == [dropped]


# `JudgedScorer._run_eval_async` reads `prepared["output"]` inside its own try block, so a
# shape that stops matching the prompt template is caught and scored 0.0 as a judge error
# on all four judges rather than raising.
def test_final_message_judge_hands_the_message_to_the_judge() -> None:
    prepared = FinalMessageJudge(name="refused_without_blaming", question="q")._prepare(
        {"last_message": "I could not change it."}, {"refused_without_blaming": {"required": True}}
    )

    assert not isinstance(prepared, Score)
    assert prepared["output"]["last_message"] == "I could not change it."


# The read-only case passes as soon as none of these landed, so a derivation that returned
# nothing would pass every run. Reading the catalog is what keeps the list current; this
# checks the reading still finds it.
def test_flag_write_tools_reads_the_generated_catalog() -> None:
    tools = flag_write_tools()

    assert "update-feature-flag" in tools
    assert "scheduled-changes-create" in tools
    assert "feature-flag-get-all" not in tools
    assert len(tools) >= 13
