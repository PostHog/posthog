"""Full-stack harness tests: real step functions, replay backend, scoring, errors.

These run the genuine ``run_multi_turn_research`` / ``select_repository_for_team`` through
the replay backend (no stack, no LLM) and assert the harness both passes a golden cassette
and *fails* a deliberately wrong one — discrimination through the entire pipeline.
"""

from __future__ import annotations

import asyncio

from products.signals.eval.agentic.cases.research import CASES as RESEARCH_CASES
from products.signals.eval.agentic.cassette import Cassette, RecordedTurn
from products.signals.eval.agentic.datasets import ResearchCase, ResearchExpectation, SignalSpec
from products.signals.eval.agentic.harness import AgenticEvalHarness
from products.signals.eval.agentic.runners import RunContext
from products.signals.eval.agentic.scorers_research import default_research_scorers


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
