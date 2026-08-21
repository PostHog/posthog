"""Scorer discrimination tests: good output passes, bad output fails.

A scorer that always passes is worthless, so every dimension is asserted in both
directions. DB-free; run with the same -o overrides as the other agentic tests.
"""

from __future__ import annotations

import asyncio

from parameterized import parameterized

from products.signals.backend.artefact_schemas import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    SignalFinding,
)
from products.signals.backend.report_generation.research import ReportResearchOutput
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.evals.agentic.datasets import (
    ImplementationCase,
    ImplementationExpectation,
    RepoSelectionCase,
    RepoSelectionExpectation,
    ResearchCase,
    ResearchExpectation,
    ScoutCase,
    ScoutExpectation,
    SignalSpec,
)
from products.signals.evals.agentic.runners import ImplementationOutput, ScoutDecisionOutput
from products.signals.evals.agentic.scorers_implementation import default_implementation_scorers
from products.signals.evals.agentic.scorers_repo_selection import (
    RepoSelectionCorrectnessScorer,
    default_repo_selection_scorers,
)
from products.signals.evals.agentic.scorers_research import DataEvidenceScorer, default_research_scorers
from products.signals.evals.agentic.scorers_scout import ScoutSummaryTermsScorer, default_scout_scorers
from products.signals.evals.agentic.scoring import ScoringContext

_CTX = ScoringContext()


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


def _good_research_output() -> ReportResearchOutput:
    return _research_output(
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
        priority=Priority.P1,
        already_addressed=False,
        paths=["posthog/hogql_queries/insights/funnels/funnel.py"],
        verified=True,
        commits={"abc1234": "introduced the bug"},
        title="fix(funnels): tz",
        summary="The funnel breaks.",
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
    results = _score(default_research_scorers(), _research_case(), _good_research_output())
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


@parameterized.expand(
    [
        ("none_acceptable_passes", ("P4", None), True),
        ("none_not_acceptable_fails", ("P2", "P3"), False),
    ]
)
def test_priority_scorer_handles_missing_priority(_name: str, acceptable: tuple, expected: bool):
    case = ResearchCase(
        case_id="rc_prio_none",
        step="research",
        signals=(SignalSpec(signal_id="s1", content="customer praise, nothing to do"),),
        expected=ResearchExpectation(expected_actionability="not_actionable", expected_priority=acceptable),
    )
    output = _good_research_output()
    output.new_artefacts = [a for a in output.new_artefacts if not isinstance(a, PriorityAssessment)]
    results = _score(default_research_scorers(), case, output)
    assert results["priority_correct"] is expected


@parameterized.expand(
    [
        (
            "query_with_result",
            "Ran execute-sql: SELECT count() FROM events WHERE event='$exception' — 4,210 checkout timeouts/day.",
            True,
        ),
        (
            "mixed_narrative_with_incidental_marker",
            "Queried $exception events: 4,210 checkout timeouts/day over the last 7 days; "
            "session recordings were not available for these users.",
            True,
        ),
        (
            "short_no_data_note",
            "No PostHog MCP queries were run; the MCP tools were not available.",
            False,
        ),
        (
            "long_no_data_note_without_results",
            "The PostHog MCP tools were not available in this sandbox, so no relevant queries could be "
            "executed against the project's analytics or error tracking data at all.",
            False,
        ),
        (
            "general_prose_without_query_or_result",
            "The available project information broadly supports investigating this issue with the engineering team.",
            False,
        ),
    ]
)
def test_data_evidence_scorer_discriminates(_name: str, data_queried: str, expected: bool):
    case = ResearchCase(
        case_id="rc_data",
        step="research",
        signals=(SignalSpec(signal_id="s1", content="checkout errors spiking"),),
        expected=ResearchExpectation(expect_data_evidence=True),
    )
    output = _good_research_output()
    finding = output.new_artefacts[0]
    assert isinstance(finding, SignalFinding)
    finding.data_queried = data_queried
    assert _score([DataEvidenceScorer()], case, output)["data_evidence_used"] is expected


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
    no_reason = RepoSelectionResult(repository="calcom/cal.com", reason="ok")
    assert _score(scorers, case, good)["repo_selected_correct"] is True
    assert _score(scorers, case, good)["repo_reason_present"] is True
    assert _score(scorers, case, wrong)["repo_selected_correct"] is False
    assert _score(scorers, case, no_reason)["repo_reason_present"] is False


@parameterized.expand([("no_expectation", None), ("empty_expected_set", ())])
def test_repo_selection_scorer_errors_without_ground_truth(_name: str, expected_repository):
    case = RepoSelectionCase(
        case_id="rs_cfg",
        step="repo_selection",
        candidate_repos=("calcom/cal.com",),
        expected=RepoSelectionExpectation(expected_repository=expected_repository),
    )
    pick = RepoSelectionResult(repository="calcom/cal.com", reason="plausible but ungraded")
    [score] = asyncio.run(RepoSelectionCorrectnessScorer().score(case, pick, _CTX))
    assert score.status == "error"
    assert score.passed is False


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

    too_broad = ImplementationOutput(
        "diff --git a/packages/lib/slots/getSchedule.ts b/packages/lib/slots/getSchedule.ts\n+ timezone\n"
        "diff --git a/packages/lib/a.ts b/packages/lib/a.ts\n+ x\n"
        "diff --git a/packages/lib/b.ts b/packages/lib/b.ts\n+ x\n"
    )
    assert _score(scorers, case, too_broad)["files_changed_count"] is False


def test_diff_file_parser_handles_dev_null_and_prefixes():
    out = ImplementationOutput("diff --git a/src/new.ts b/src/new.ts\n--- /dev/null\n+++ b/src/new.ts\n+content\n")
    assert out.files_changed == ["src/new.ts"]


def test_scout_forbidden_term_normalized_before_match():
    case = ScoutCase(
        case_id="scout_forbidden_norm",
        step="scout",
        expected=ScoutExpectation(expected_decision="emit_report", forbidden_summary_terms=("2,240",)),
    )
    output = ScoutDecisionOutput(
        decision="emit_report",
        summary="Affected 2,240 sessions in the last hour.",
        evidence=[],
        actionability="immediately_actionable",
        priority="P2",
        existing_report_id=None,
        scratchpad_keys=[],
        suggested_reviewers=[],
        repository=None,
    )

    assert _score([ScoutSummaryTermsScorer()], case, output)["scout_summary_forbidden_terms"] is False


def test_scout_scorers_discriminate():
    case = ScoutCase(
        case_id="scout_eval",
        step="scout",
        expected=ScoutExpectation(
            expected_decision="edit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P2", "P3"),
            expected_existing_report_id="rpt_existing",
            expected_repository="acme/webapp",
            min_evidence_items=2,
            required_summary_terms=("burst", "checkout"),
            forbidden_summary_terms=("duplicate",),
            required_scratchpad_keys=("dedupe:checkout",),
        ),
    )
    scorers = default_scout_scorers()
    good = ScoutDecisionOutput(
        decision="edit_report",
        summary="Checkout burst should update the existing report.",
        evidence=["1,400 affected sessions", "started after release"],
        actionability="requires_human_input",
        priority="P2",
        existing_report_id="rpt_existing",
        scratchpad_keys=["dedupe:checkout"],
        suggested_reviewers=[],
        repository="acme/webapp",
    )
    res_good = _score(scorers, case, good)
    assert res_good["scout_decision_correct"]
    assert res_good["scout_actionability_correct"]
    assert res_good["scout_priority_correct"]
    assert res_good["scout_existing_report_correct"]
    assert res_good["scout_repository_correct"]
    assert res_good["scout_evidence_count"]
    assert res_good["scout_scratchpad_keys"]
    assert res_good["scout_summary_required_terms"]
    assert res_good["scout_summary_forbidden_terms"]

    bad = ScoutDecisionOutput(
        decision="emit_report",
        summary="Duplicate unrelated issue.",
        evidence=["single weak signal"],
        actionability="not_actionable",
        priority="P4",
        existing_report_id="rpt_other",
        scratchpad_keys=[],
        suggested_reviewers=[],
        repository="acme/api",
    )
    res_bad = _score(scorers, case, bad)
    assert res_bad["scout_decision_correct"] is False
    assert res_bad["scout_actionability_correct"] is False
    assert res_bad["scout_priority_correct"] is False
    assert res_bad["scout_existing_report_correct"] is False
    assert res_bad["scout_repository_correct"] is False
    assert res_bad["scout_evidence_count"] is False
    assert res_bad["scout_scratchpad_keys"] is False
    assert res_bad["scout_summary_required_terms"] is False
    assert res_bad["scout_summary_forbidden_terms"] is False


def test_scout_forbidden_terms_use_summary_normalization():
    case = ScoutCase(
        case_id="normalized_forbidden",
        step="scout",
        expected=ScoutExpectation(expected_decision="skip", forbidden_summary_terms=("2,240",)),
    )
    output = ScoutDecisionOutput(decision="skip", summary="The issue affected 2240 sessions.")

    assert _score(default_scout_scorers(), case, output)["scout_summary_forbidden_terms"] is False
