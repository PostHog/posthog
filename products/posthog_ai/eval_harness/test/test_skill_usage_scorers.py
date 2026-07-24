from __future__ import annotations

import pytest

from braintrust import Score

from products.posthog_ai.eval_harness.test.test_skill_distribution_scorers import _exec, _output, _score, _tool_call
from products.posthog_ai.evals.cli_mcp.skill_usage_scorers import (
    ExpectedReferencePulled,
    SearchRecoveryAfterZeroHit,
    SkillAnswerCorrectness,
)

ZERO_HIT = 'No skills matched "xyz". None of the query words appear in any skill.'


def _ref_expected(
    paths: list[str], *, skill: str = "s", source: str = "posthog", delivery: str = "exec"
) -> dict[str, dict[str, object]]:
    return {"expected_reference_pulled": {"skill": skill, "delivery": delivery, "source": source, "paths": paths}}


def _recovery_expected() -> dict[str, dict[str, object]]:
    return {"search_recovery_after_zero_hit": {}}


@pytest.mark.parametrize(
    "command,paths,skill,source",
    [
        ("learn posthog:s references/a.md", ["references/a.md"], "s", "posthog"),
        ("learn posthog:s references/a.md references/b.md", ["references/b.md"], "s", "posthog"),
        ("learn posthog:s references/a.md -s query", ["references/a.md"], "s", "posthog"),
        ("learn posthog:s references/a.md --lines 1:40", ["references/a.md"], "s", "posthog"),
        ("learn project:p references/policy-details.md", ["references/policy-details.md"], "p", "project"),
        ("learn posthog:s ./references/a.md", ["references/a.md"], "s", "posthog"),
    ],
)
def test_expected_reference_pulled_accepts_exec_reference_reads(
    command: str, paths: list[str], skill: str, source: str
) -> None:
    output = _output(_exec("ref", command))
    expected = _ref_expected(paths, skill=skill, source=source)
    assert _score(ExpectedReferencePulled(), output, expected).score == 1.0


@pytest.mark.parametrize(
    "command,paths,skill,failed",
    [
        ("learn posthog:s", ["references/a.md"], "s", False),
        ("learn posthog:s SKILL.md", ["references/a.md"], "s", False),
        ("learn posthog:other references/a.md", ["references/a.md"], "s", False),
        ("learn posthog:s references/a.md", ["references/a.md"], "s", True),
        ("learn posthog:s posthog:other", ["references/a.md"], "s", False),
        ("learn posthog:s -s query", ["references/a.md"], "s", False),
    ],
)
def test_expected_reference_pulled_rejects_non_reference_exec_calls(
    command: str, paths: list[str], skill: str, failed: bool
) -> None:
    output = _output(_exec("ref", command, failed=failed))
    assert _score(ExpectedReferencePulled(), output, _ref_expected(paths, skill=skill)).score == 0.0


@pytest.mark.parametrize(
    "file_path,expected_score",
    [
        ("/root/.claude/skills/s/references/a.md", 1.0),
        ("/root/.claude/skills/s/references/unrelated.md", 0.0),
    ],
)
def test_expected_reference_pulled_bundled_arm_matches_reference_file_path(
    file_path: str, expected_score: float
) -> None:
    output = _output(_tool_call("read", "Read", {"file_path": file_path}))
    expected = _ref_expected(["references/a.md"], delivery="bundled")
    assert _score(ExpectedReferencePulled(), output, expected).score == expected_score


def test_expected_reference_pulled_self_skips_when_not_requested() -> None:
    output = _output(_exec("ref", "learn posthog:s references/a.md"))
    assert _score(ExpectedReferencePulled(), output, {}).score is None


@pytest.mark.parametrize(
    "calls,expected_score",
    [
        ([_exec("search", "learn -s revenue", "posthog:s")], None),
        ([_exec("zero", "learn -s xyz", ZERO_HIT), _exec("recover", "learn skills", "posthog:s")], 1.0),
        ([_exec("zero", "learn -s xyz", ZERO_HIT), _exec("recover", "learn -s broader", "posthog:s")], 1.0),
        ([_exec("zero", "learn -s xyz", ZERO_HIT), _exec("give-up", "call execute-sql {}", "[]")], 0.0),
        # A gate-rejected (errored) product call is still the agent jumping to product
        # tools — a later learn must not hide it from the ordering.
        (
            [
                _exec("zero", "learn -s xyz", ZERO_HIT),
                _exec("gated", "call execute-sql {}", "No skills loaded this session.", failed=True),
                _exec("recover", "learn skills", "posthog:s"),
            ],
            0.0,
        ),
        ([_exec("zero", "learn -s xyz", ZERO_HIT)], 0.0),
        ([_exec("zero", "learn -s xyz", ZERO_HIT, failed=True)], None),
        (
            [
                _exec("zero-1", "learn -s xyz", ZERO_HIT),
                _exec("zero-2", "learn -s abc", ZERO_HIT),
                _exec("give-up", "call execute-sql {}", "[]"),
            ],
            0.0,
        ),
    ],
)
def test_search_recovery_after_zero_hit(calls: list[list[str]], expected_score: float | None) -> None:
    result = _score(SearchRecoveryAfterZeroHit(), _output(*calls), _recovery_expected())
    if expected_score is None:
        assert result.score is None
    else:
        assert result.score == expected_score


def test_skill_answer_correctness_self_skips_when_not_requested() -> None:
    prepared = SkillAnswerCorrectness()._prepare({"last_message": "anything"}, {})
    assert isinstance(prepared, Score)
    assert prepared.score is None


def test_skill_answer_correctness_fails_without_final_message() -> None:
    expected = {"skill_answer_correctness": {"expected_answer": "the answer"}}
    prepared = SkillAnswerCorrectness()._prepare({"last_message": "  "}, expected)
    assert isinstance(prepared, Score)
    assert prepared.score == 0.0


def test_skill_answer_correctness_forwards_answer_to_judge() -> None:
    expected = {"skill_answer_correctness": {"expected_answer": "the answer"}}
    output = {"last_message": "some final answer", "prompt": "the question"}
    prepared = SkillAnswerCorrectness()._prepare(output, expected)
    assert isinstance(prepared, dict)
    assert prepared["expected"]["expected_answer"] == "the answer"
    assert prepared["output"]["final_message"] == "some final answer"
