import asyncio

from products.posthog_ai.eval_harness.scorers.contract import Score
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.evals.agentic.braintrust import (
    ImplementationFixJudge,
    RepositorySelectionJudge,
    ResearchSummaryJudge,
    SignalsScorerAdapter,
    decode_repo_selection,
)
from products.signals.evals.agentic.datasets import (
    ImplementationCase,
    RepoSelectionCase,
    RepoSelectionExpectation,
    ResearchCase,
)
from products.signals.evals.agentic.runners import RepoSelectionOutput
from products.signals.evals.agentic.scorers_repo_selection import RepoSelectionCorrectnessScorer


def test_adapter_exposes_domain_score_to_braintrust() -> None:
    case = RepoSelectionCase(
        case_id="public-repo",
        step="repo_selection",
        expected=RepoSelectionExpectation(expected_repository="posthog/posthog-js"),
    )
    adapter = SignalsScorerAdapter(RepoSelectionCorrectnessScorer(), [case], decode_repo_selection)
    output = RepoSelectionResult(repository="posthog/posthog-js", reason="browser SDK").model_dump(mode="json")

    score = asyncio.run(adapter._run_eval_async(output, {"case_id": case.case_id}))

    assert score.name == "repo_selected_correct"
    assert score.score == 1.0
    assert score.metadata["passed"] is True


def test_implementation_judge_fails_closed_without_captured_diff() -> None:
    case = ImplementationCase(
        case_id="implementation",
        step="implementation",
        repo="posthog/hedgebox",
        issue_prompt="make a focused change",
    )
    judge = ImplementationFixJudge([case])

    score = judge._prepare({"diff": "", "files_changed": []}, {"case_id": case.case_id})

    assert isinstance(score, Score)
    assert score.score == 0.0
    assert score.metadata["reason"] == "no actual diff captured"


def test_research_judge_includes_reference_facts_and_seeded_data() -> None:
    case = ResearchCase(
        case_id="research",
        step="research",
        judging_notes="Conversion stayed at 60% while entrant volume fell.",
    )
    judge = ResearchSummaryJudge([case])

    prepared = judge._prepare(
        {
            "title": "Signup volume fell",
            "summary": "Signup conversion is stable.",
            "new_artefacts": [],
            "seed": {"baseline_conversion": 0.6, "latest_conversion": 0.6},
        },
        {"case_id": case.case_id},
    )

    assert isinstance(prepared, dict)
    assert "Conversion stayed at 60%" in prepared["expected"]
    assert '"latest_conversion": 0.6' in prepared["expected"]


def test_implementation_judge_includes_hidden_acceptance_notes() -> None:
    case = ImplementationCase(
        case_id="implementation",
        step="implementation",
        repo="posthog/hedgebox",
        issue_prompt="fix downloads",
        judging_notes="Both download entry points must use one helper.",
    )
    judge = ImplementationFixJudge([case])

    prepared = judge._prepare(
        {"diff": "diff --git a/src/a.ts b/src/a.ts\n", "raw_log": ""},
        {"case_id": case.case_id},
    )

    assert isinstance(prepared, dict)
    assert "Both download entry points" in prepared["expected"]
    assert '"diff": "diff --git' in prepared["output"]


def test_repository_selection_judge_includes_reference_evidence() -> None:
    case = RepoSelectionCase(
        case_id="ambiguous",
        step="repo_selection",
        signals=(),
        candidate_repos=("excalidraw/excalidraw", "tldraw/tldraw"),
        judging_notes="Excalidraw owns staticSvgScene.ts.",
        expected=RepoSelectionExpectation(expected_repository="excalidraw/excalidraw"),
    )
    judge = RepositorySelectionJudge([case])

    prepared = judge._prepare(
        RepoSelectionOutput(
            repository="excalidraw/excalidraw",
            reason="staticSvgScene.ts matches",
            raw_log="",
        ).model_dump(mode="json"),
        {"case_id": case.case_id},
    )

    assert isinstance(prepared, dict)
    assert "staticSvgScene.ts" in prepared["expected"]
    assert "excalidraw/excalidraw" in prepared["output"]
    assert '"repository_evidence_used": false' in prepared["output"]
