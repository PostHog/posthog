from __future__ import annotations

import json
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
    RepoSelectionCase,
    RepoSelectionExpectation,
    ResearchCase,
    ResearchExpectation,
    ScoutCase,
    ScoutExpectation,
    SignalSpec,
)
from products.signals.evals.agentic.runners import (
    ImplementationOutput,
    RepoSelectionOutput,
    ScoutOutput,
    _scout_outcome,
)
from products.signals.evals.agentic.scorers_repo_selection import (
    RepoSelectionCorrectnessScorer,
    RepositoryEvidenceScorer,
    default_repo_selection_scorers,
)
from products.signals.evals.agentic.scorers_research import default_research_scorers
from products.signals.evals.agentic.scorers_scout import default_scout_scorers
from products.signals.evals.agentic.scoring import ScoringContext

_CTX = ScoringContext()


def _score(scorers, case, output) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for scorer in scorers:
        for score in asyncio.run(scorer.score(case, output, _CTX)):
            out[score.name] = score.passed
    return out


def _research_output(*, actionability, priority, already_addressed, verified):
    return ReportResearchOutput(
        title="Funnel regression",
        summary="The funnel breaks.",
        new_artefacts=[
            SignalFinding(signal_id="s1", relevant_code_paths=[], data_queried="queried events", verified=verified),
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
        verified=True,
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
        ),
    )


def test_research_scorers_pass_on_good_output():
    results = _score(default_research_scorers(), _research_case(), _good_research_output())
    assert all(results.values()), results


def test_research_scorers_fail_on_bad_output():
    output = _research_output(
        actionability=ActionabilityChoice.NOT_ACTIONABLE,
        priority=Priority.P4,
        already_addressed=True,
        verified=False,
    )
    results = _score(default_research_scorers(), _research_case(), output)
    assert results == {
        "actionability_correct": False,
        "priority_correct": False,
        "already_addressed_correct": False,
        "findings_verified": False,
    }


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
    assert _score(default_research_scorers(), case, output)["priority_correct"] is expected


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


def _repository_cache_log(command: str, output: str = "excalidraw/excalidraw") -> str:
    updates = [
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "tool-1",
            "title": "PostHog",
            "rawInput": {"command": command},
            "_meta": {"claudeCode": {"toolName": "mcp__posthog__exec"}},
        },
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tool-1",
            "status": "completed",
            "rawOutput": output,
        },
    ]
    return "\n".join(
        json.dumps(
            {
                "timestamp": "2026-08-21T12:00:00Z",
                "notification": {
                    "method": "session/update",
                    "params": {"update": update},
                },
            }
        )
        for update in updates
    )


def test_repository_evidence_scorer_requires_successful_cache_query():
    case = RepoSelectionCase(
        case_id="rs_evidence",
        step="repo_selection",
        candidate_repos=("excalidraw/excalidraw", "tldraw/tldraw"),
        expected=RepoSelectionExpectation(expected_repository="excalidraw/excalidraw"),
    )
    scorer = RepositoryEvidenceScorer()
    grounded = RepoSelectionOutput(
        repository="excalidraw/excalidraw",
        reason="matched staticSvgScene.ts",
        raw_log=_repository_cache_log(
            'call execute-sql {"query":"SELECT tree_paths FROM system.integration_repository_cache"}'
        ),
    )
    guessed = RepoSelectionOutput(
        repository="excalidraw/excalidraw",
        reason="the identifier sounds familiar",
        raw_log=_repository_cache_log("cat /tmp/query.sql"),
    )

    assert _score([scorer], case, grounded)["repository_evidence_used"] is True
    assert _score([scorer], case, guessed)["repository_evidence_used"] is False


@parameterized.expand([("no_expectation", None), ("empty_expected_set", ())])
def test_repo_selection_scorer_errors_without_ground_truth(_name: str, expected_repository):
    case = RepoSelectionCase(
        case_id="rs_cfg",
        step="repo_selection",
        candidate_repos=("calcom/cal.com",),
        expected=RepoSelectionExpectation(expected_repository=expected_repository),
    )
    output = RepoSelectionResult(repository="calcom/cal.com", reason="plausible but ungraded")
    [score] = asyncio.run(RepoSelectionCorrectnessScorer().score(case, output, _CTX))
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


def test_diff_file_parser_handles_dev_null_and_prefixes():
    output = ImplementationOutput("diff --git a/src/new.ts b/src/new.ts\n--- /dev/null\n+++ b/src/new.ts\n+content\n")
    assert output.files_changed == ["src/new.ts"]


@parameterized.expand(
    [
        ("report", ["report-id"], [], [], [], "emit_report"),
        ("edit", [], ["report-id"], [], [], "edit_report"),
        ("signal", [], [], ["finding-id"], [], "emit_signal"),
        ("memory", [], [], [], ["baseline:key"], "remember"),
        ("quiet", [], [], [], [], "no_output"),
    ]
)
def test_scout_outcome_uses_persisted_effects(_name, reports, edits, findings, memory, expected):
    assert _scout_outcome(reports, edits, findings, memory) == expected


def test_scout_outcome_scorer_discriminates():
    case = ScoutCase(
        case_id="scout_eval",
        step="scout",
        expected_query_tools=("query-funnel",),
        expected=ScoutExpectation(expected_outcome="emit_report"),
    )
    good = ScoutOutput(
        outcome="emit_report",
        summary="Created a report",
        raw_log=_repository_cache_log('call query-funnel {"date_from":"-7d"}'),
    )
    bad = ScoutOutput(outcome="no_output", summary="Quiet")
    assert _score(default_scout_scorers(), case, good)["scout_outcome_correct"] is True
    assert _score(default_scout_scorers(), case, bad)["scout_outcome_correct"] is False
    assert _score(default_scout_scorers(), case, good)["project_data_queried"] is True
    assert _score(default_scout_scorers(), case, bad)["project_data_queried"] is False
