import asyncio

from products.posthog_ai.eval_harness.scorers.contract import Score
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.eval.agentic.braintrust import ImplementationFixJudge, SignalsScorerAdapter, decode_repo_selection
from products.signals.eval.agentic.datasets import ImplementationCase, RepoSelectionCase, RepoSelectionExpectation
from products.signals.eval.agentic.scorers_repo_selection import RepoSelectionCorrectnessScorer


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
