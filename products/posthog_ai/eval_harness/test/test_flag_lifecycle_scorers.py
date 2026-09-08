from __future__ import annotations

import json
from typing import Any

from parameterized import parameterized

from products.feature_flags.evals.scorers import (
    AvoidedTool,
    CalledExpectedTool,
    CreatedFlagWithTags,
    FinalMessageJudge,
    GenericUpdateOmitsFields,
    PreservedUnrelatedConfig,
)
from products.feature_flags.evals.seeders import (
    ROLLOUT_FROM_PERCENTAGE,
    ROLLOUT_INITIAL_FILTERS,
    ROLLOUT_PINNED_PERCENTAGE,
    ROLLOUT_TO_PERCENTAGE,
)
from products.posthog_ai.eval_harness.scorers.contract import Score

CREATE_TOOL = "create-feature-flag"
UPDATE_TOOL = "update-feature-flag"


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
        (AvoidedTool(), "avoided_tool"),
        (GenericUpdateOmitsFields(), "generic_update_omits_fields"),
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
