"""Scorer discrimination tests: good output passes, bad output fails.

A scorer that always passes is worthless, so every dimension is asserted in both
directions. DB-free; run with the same -o overrides as the other agentic tests.
"""

from __future__ import annotations

import asyncio

from products.signals.backend.artefact_schemas import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    SignalFinding,
)
from products.signals.backend.report_generation.research import ReportResearchOutput
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.eval.agentic.datasets import (
    ImplementationCase,
    ImplementationExpectation,
    RepoSelectionCase,
    RepoSelectionExpectation,
    ResearchCase,
    ResearchExpectation,
    SignalSpec,
)
from products.signals.eval.agentic.runners import ImplementationOutput
from products.signals.eval.agentic.scorers_implementation import default_implementation_scorers
from products.signals.eval.agentic.scorers_repo_selection import default_repo_selection_scorers
from products.signals.eval.agentic.scorers_research import default_research_scorers
from products.signals.eval.agentic.scoring import ScoringContext

_CTX = ScoringContext(judge=None)


def _score(scorers, case, output) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for scorer in scorers:
        for s in asyncio.run(scorer.score(case, output, _CTX)):
            out[s.name] = s.passed
    return out


def _research_output(*, actionability, priority, already_addressed, paths, verified, commits, title, summary):
    return ReportResearchOutput(
        title=title,
        summary=summary,
        new_artefacts=[
            SignalFinding(
                signal_id="s1",
                relevant_code_paths=paths,
                relevant_commit_hashes=commits,
                data_queried="queried events",
                verified=verified,
            ),
            ActionabilityAssessment(
                explanation="because reasons",
                actionability=actionability,
                already_addressed=already_addressed,
            ),
            PriorityAssessment(explanation="impact", priority=priority, dollar_value=1.0),
        ],
    )


def _research_case() -> ResearchCase:
    return ResearchCase(
        case_id="rc",
        step="research",
        signals=(SignalSpec(signal_id="s1", content="funnel broke"),),
        expected=ResearchExpectation(
            expected_actionability="immediately_actionable",
            expected_priority="P1",
            expected_already_addressed=False,
            expect_verified=True,
            expected_code_path_substrings={"s1": ("funnel",)},
            summary_must_mention=("funnel",),
            min_commit_hashes=1,
        ),
    )


def test_research_scorers_pass_on_good_output():
    good = _research_output(
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
        priority=Priority.P1,
        already_addressed=False,
        paths=["posthog/hogql_queries/insights/funnels/funnel.py"],
        verified=True,
        commits={"abc1234": "introduced the bug"},
        title="fix(funnels): tz",
        summary="The funnel breaks.",
    )
    results = _score(default_research_scorers(), _research_case(), good)
    assert all(results.values()), results


def test_research_scorers_fail_on_bad_output():
    bad = _research_output(
        actionability=ActionabilityChoice.NOT_ACTIONABLE,  # wrong
        priority=Priority.P4,  # wrong
        already_addressed=True,  # wrong
        paths=["posthog/unrelated/module.py"],  # no 'funnel'
        verified=False,  # wrong
        commits={},  # below min
        title="misc",
        summary="various issues",  # no 'funnel'
    )
    results = _score(default_research_scorers(), _research_case(), bad)
    assert results["actionability_correct"] is False
    assert results["priority_correct"] is False
    assert results["already_addressed_correct"] is False
    assert results["code_paths_found"] is False
    assert results["findings_verified"] is False
    assert results["commit_attribution"] is False
    assert results["summary_mentions"] is False


def test_data_evidence_scorer_discriminates():
    from products.signals.eval.agentic.scorers_research import DataEvidenceScorer

    case = ResearchCase(
        case_id="rc_data",
        step="research",
        signals=(SignalSpec(signal_id="s1", content="checkout errors spiking"),),
        expected=ResearchExpectation(expect_data_evidence=True),
    )
    scorer = DataEvidenceScorer()
    queried = _research_output(
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
        priority=Priority.P1,
        already_addressed=False,
        paths=["a.py"],
        verified=True,
        commits={"abc1234": "x"},
        title="t",
        summary="s",
    )
    queried.new_artefacts[
        0
    ].data_queried = (
        "Ran execute-sql: SELECT count() FROM events WHERE event='$exception' — 4,210 checkout timeouts/day."
    )
    assert _score([scorer], case, queried)["data_evidence_used"] is True

    no_data = _research_output(
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
        priority=Priority.P1,
        already_addressed=False,
        paths=["a.py"],
        verified=False,
        commits={"abc1234": "x"},
        title="t",
        summary="s",
    )
    no_data.new_artefacts[0].data_queried = "No PostHog MCP queries were run; the MCP tools were not available."
    assert _score([scorer], case, no_data)["data_evidence_used"] is False


def test_repo_selection_scorer_discriminates():
    case = RepoSelectionCase(
        case_id="rs",
        step="repo_selection",
        candidate_repos=("calcom/cal.com", "supabase/supabase"),
        expected=RepoSelectionExpectation(expected_repository="calcom/cal.com"),
    )
    scorers = default_repo_selection_scorers()
    good = RepoSelectionResult(repository="calcom/cal.com", reason="clear match to scheduling")
    wrong = RepoSelectionResult(repository="supabase/supabase", reason="clear match to scheduling")
    assert _score(scorers, case, good)["repo_selected_correct"] is True
    assert _score(scorers, case, wrong)["repo_selected_correct"] is False


def test_repo_selection_null_case():
    case = RepoSelectionCase(
        case_id="rsn",
        step="repo_selection",
        candidate_repos=("calcom/cal.com",),
        expected=RepoSelectionExpectation(expect_null=True),
    )
    scorers = default_repo_selection_scorers()
    null = RepoSelectionResult(repository=None, reason="no candidate owns billing operations")
    picked = RepoSelectionResult(repository="calcom/cal.com", reason="no candidate owns billing operations")
    assert _score(scorers, case, null)["repo_selected_correct"] is True
    assert _score(scorers, case, picked)["repo_selected_correct"] is False


def test_implementation_scorers_discriminate():
    case = ImplementationCase(
        case_id="impl",
        step="implementation",
        repo="cal",
        issue_prompt="fix tz",
        expected=ImplementationExpectation(
            expected_file_substrings=("getschedule",),
            forbidden_file_substrings=("pnpm-lock",),
            expected_diff_keywords=("timezone",),
            min_files_changed=1,
            max_files_changed=2,
        ),
    )
    scorers = default_implementation_scorers()
    good = ImplementationOutput(
        "diff --git a/packages/lib/slots/getSchedule.ts b/packages/lib/slots/getSchedule.ts\n"
        "--- a/packages/lib/slots/getSchedule.ts\n"
        "+++ b/packages/lib/slots/getSchedule.ts\n"
        "+ // normalize to organizer timezone\n"
    )
    res_good = _score(scorers, case, good)
    assert res_good["expected_files_touched"] and res_good["no_forbidden_files"]
    assert res_good["diff_keywords_present"] and res_good["files_changed_count"]

    bad = ImplementationOutput(
        "diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml\n--- a/pnpm-lock.yaml\n+++ b/pnpm-lock.yaml\n+ random churn\n"
    )
    res_bad = _score(scorers, case, bad)
    assert res_bad["expected_files_touched"] is False
    assert res_bad["no_forbidden_files"] is False
    assert res_bad["diff_keywords_present"] is False


def test_diff_file_parser_handles_dev_null_and_prefixes():
    out = ImplementationOutput("diff --git a/src/new.ts b/src/new.ts\n--- /dev/null\n+++ b/src/new.ts\n+content\n")
    assert out.files_changed == ["src/new.ts"]
