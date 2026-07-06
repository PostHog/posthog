"""Scorer discrimination tests: good output passes, bad output fails.

A scorer that always passes is worthless, so every dimension is asserted in both
directions. DB-free; run with the same -o overrides as the other agentic tests.
"""

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
from products.signals.eval.agentic.cases import generated
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
from products.signals.eval.agentic.scorers_judge import ImplementationFixJudge, ResearchSummaryJudge
from products.signals.eval.agentic.scorers_repo_selection import (
    RepoSelectionCorrectnessScorer,
    default_repo_selection_scorers,
)
from products.signals.eval.agentic.scorers_research import DataEvidenceScorer, default_research_scorers
from products.signals.eval.agentic.scoring import JudgeVerdict, ScoringContext

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


def _fake_judge(score: float):
    async def judge(*, system: str, prompt: str, rubric: str | None = None) -> JudgeVerdict:
        assert system and prompt
        return JudgeVerdict(passed=score >= 0.6, score=score, reasoning="fake judge")

    return judge


@parameterized.expand([("above_threshold", 0.9, True), ("below_threshold", 0.3, False)])
def test_judge_scorers_map_score_to_verdict(_name: str, judge_score: float, expected: bool):
    ctx = ScoringContext(judge=_fake_judge(judge_score))
    [research_score] = asyncio.run(ResearchSummaryJudge().score(_research_case(), _good_research_output(), ctx))
    assert research_score.passed is expected
    assert research_score.status == "ok"
    impl_case = ImplementationCase(case_id="impl_j", step="implementation", repo="cal", issue_prompt="fix tz")
    impl_out = ImplementationOutput("diff --git a/a.ts b/a.ts\n+++ b/a.ts\n+ fix\n")
    [impl_score] = asyncio.run(ImplementationFixJudge().score(impl_case, impl_out, ctx))
    assert impl_score.passed is expected
    assert impl_score.status == "ok"


def test_judge_scorers_skip_when_judge_disabled():
    [score] = asyncio.run(ResearchSummaryJudge().score(_research_case(), _good_research_output(), _CTX))
    assert score.status == "skipped"
    assert score.passed is False


def test_generated_loader_skips_malformed_and_duplicate_rows(tmp_path, monkeypatch):
    rows = [
        {"case_id": "ok_1", "signal": {"content": "checkout errors spiking"}, "expectation": {}},
        {"case_id": "bad_1", "signal": {}},  # missing content
        {"case_id": "dup_1", "signal": {"content": "checkout errors spiking"}, "expectation": {}},
    ]
    (tmp_path / "research.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "repo_selection.json").write_text("[{", encoding="utf-8")  # truncated file
    monkeypatch.setattr(generated, "GENERATED_DIR", tmp_path)
    assert [c.case_id for c in generated.load_generated_research()] == ["ok_1"]
    assert generated.load_generated_repo_selection() == []
