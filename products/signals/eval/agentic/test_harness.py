"""Full-stack harness tests: real step functions, replay backend, scoring, errors.

These run the genuine ``run_multi_turn_research`` / ``select_repository_for_team`` through
the replay backend (no stack, no LLM) and assert the harness both passes a golden cassette
and *fails* a deliberately wrong one — discrimination through the entire pipeline.
"""

from __future__ import annotations

import asyncio

import pytest

from products.signals.eval.agentic.cases.research import CASES as RESEARCH_CASES
from products.signals.eval.agentic.cassette import Cassette, RecordedTurn
from products.signals.eval.agentic.datasets import ResearchCase, ResearchExpectation, SignalSpec
from products.signals.eval.agentic.harness import AgenticEvalHarness
from products.signals.eval.agentic.runners import (
    RUNNERS,
    RunContext,
    RunnerError,
    _files_from_diff,
    _save_recorded_cassette,
)
from products.signals.eval.agentic.scorers_research import default_research_scorers
from products.signals.eval.agentic.session_backends import _Recorder


def test_golden_research_case_passes():
    suite = asyncio.run(AgenticEvalHarness().run_suite("research", [RESEARCH_CASES[0]], mode="replay"))
    assert suite.cases[0].passed, suite.cases[0].scores


def _bad_priority_cassette(tmp_path):
    turns = [
        RecordedTurn(
            index=0,
            label="initial turn",
            model="SignalFinding",
            raw_text='{"signal_id": "s1", "relevant_code_paths": ["a/funnel.py"], '
            '"relevant_commit_hashes": {"abc1234": "cause"}, "data_queried": "q", "verified": true}',
        ),
        RecordedTurn(
            index=1,
            label="actionability",
            model="ActionabilityAssessment",
            raw_text='{"explanation": "x", "actionability": "immediately_actionable", "already_addressed": false}',
        ),
        RecordedTurn(
            index=2,
            label="priority",
            model="PriorityAssessment",
            raw_text='{"explanation": "x", "priority": "P4", "dollar_value": 1}',
        ),
        RecordedTurn(
            index=3,
            label="presentation",
            model="ReportPresentationOutput",
            raw_text='{"title": "fix(funnels): tz", "summary": "The funnel broke."}',
        ),
    ]
    cassette = Cassette(case_id="bad", step="research", turns=turns)
    cassette.save(tmp_path / "bad.json")
    return ResearchCase(
        case_id="bad",
        step="research",
        cassette="bad.json",
        signals=(SignalSpec(signal_id="s1", content="funnel broke"),),
        expected=ResearchExpectation(
            expected_actionability="immediately_actionable",  # cassette matches -> passes
            expected_priority="P1",  # cassette says P4 -> must fail
        ),
        scorers=default_research_scorers(),
    )


def test_wrong_cassette_fails_the_right_scorer(tmp_path):
    case = _bad_priority_cassette(tmp_path)
    harness = AgenticEvalHarness(ctx=RunContext(cassette_dir=tmp_path))
    suite = asyncio.run(harness.run_suite("research", [case], mode="replay"))
    result = suite.cases[0]
    assert result.passed is False
    by_name = {s.name: s for s in result.scores}
    assert by_name["priority_correct"].passed is False
    # The other dimensions still pass — failure is localized, not a blanket fail.
    assert by_name["actionability_correct"].passed is True


def test_missing_cassette_is_a_failed_case_not_a_crash():
    case = ResearchCase(
        case_id="nocassette",
        step="research",
        cassette="does_not_exist.json",
        signals=(SignalSpec(content="x"),),
        scorers=default_research_scorers(),
    )
    suite = asyncio.run(AgenticEvalHarness().run_suite("research", [case], mode="replay"))
    assert suite.cases[0].error is not None
    assert suite.cases[0].passed is False


def test_live_case_timeout_is_an_errored_result_not_a_hang(monkeypatch):
    class _WedgedRunner:
        step = "research"

        async def run(self, case, *, mode, ctx, meta=None):
            await asyncio.sleep(30)

        def input_repr(self, case):
            return ""

        def output_repr(self, output):
            return ""

    monkeypatch.setitem(RUNNERS, "research", _WedgedRunner())
    case = ResearchCase(case_id="wedged", step="research", signals=(SignalSpec(content="x"),))
    result = asyncio.run(AgenticEvalHarness(case_timeout_s=0.05).run_case(case, mode="live"))
    assert result.error is not None and "TimeoutError" in result.error
    assert result.passed is False


def test_record_refuses_to_overwrite_cassette_with_zero_turns(tmp_path):
    (tmp_path / "good.json").write_text("{}")
    case = ResearchCase(case_id="t", step="research", cassette="good.json")
    with pytest.raises(RunnerError, match="captured no turns"):
        _save_recorded_cassette(
            _Recorder(case_id="t", step="research", turns=[]), case, RunContext(cassette_dir=tmp_path)
        )
    assert (tmp_path / "good.json").read_text() == "{}"


@pytest.mark.parametrize(
    "diff,expected",
    [
        (
            # A removed `-- SQL comment` body line renders as `--- ...` and must not become a file.
            "diff --git a/prisma/migrations/1/migration.sql b/prisma/migrations/1/migration.sql\n"
            "index 1111111..2222222 100644\n"
            "--- a/prisma/migrations/1/migration.sql\n"
            "+++ b/prisma/migrations/1/migration.sql\n"
            "@@ -1,3 +1,2 @@\n"
            "--- AlterTable\n"
            '-ALTER TABLE "a" DROP COLUMN "b";\n'
            "+++ AddIndex\n",
            ["prisma/migrations/1/migration.sql"],
        ),
        (
            "diff --git a/src/a.ts b/src/a.ts\n"
            "--- a/src/a.ts\n"
            "+++ b/src/a.ts\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
            "diff --git a/src/new.ts b/src/new.ts\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new.ts\n"
            "@@ -0,0 +1 @@\n"
            "+z\n",
            ["src/a.ts", "src/new.ts"],
        ),
        (
            "diff --git a/old.ts b/new.ts\nsimilarity index 100%\nrename from old.ts\nrename to new.ts\n",
            ["old.ts", "new.ts"],
        ),
    ],
)
def test_files_from_diff_parses_real_headers_only(diff: str, expected: list[str]):
    assert _files_from_diff(diff) == expected
