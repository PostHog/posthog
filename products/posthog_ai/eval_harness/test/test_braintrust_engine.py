from __future__ import annotations

from typing import Any

import pytest
from unittest.mock import MagicMock

from braintrust import framework as bt_framework
from braintrust.framework import EvalResult, EvalResultWithSummary
from braintrust.logger import ExperimentSummary, ScoreSummary

from products.posthog_ai.eval_harness.engines.braintrust import BraintrustEngine
from products.posthog_ai.eval_harness.engines.types import CaseHooks, CaseSpec, ExperimentResult, ExperimentSpec
from products.posthog_ai.eval_harness.harness.trial_stats import trial_stats


def _summary(**overrides: Any) -> ExperimentSummary:
    defaults: dict[str, Any] = {
        "project_name": "p",
        "project_id": None,
        "experiment_id": None,
        "experiment_name": "exp",
        "project_url": None,
        "experiment_url": None,
        "comparison_experiment_name": None,
        "scores": {"acc": ScoreSummary("acc", 3, 0.5, None, None)},
        "metrics": {},
    }
    defaults.update(overrides)
    return ExperimentSummary(**defaults)


def test_translate_preserves_none_scores_and_stringifies_errors() -> None:
    result: EvalResultWithSummary = EvalResultWithSummary(
        summary=_summary(experiment_url="https://bt.example/e"),
        results=[
            EvalResult(input={"name": "a"}, output={"v": 1}, scores={"acc": 1.0}, expected={"e": 1}, metadata={"m": 1}),
            EvalResult(input={"name": "skip"}, output={}, scores={"acc": None}, metadata={}),
            EvalResult(input={"name": "boom"}, output=None, scores={}, error=ValueError("infra boom")),
            EvalResult(
                input={"name": "scorer-error"},
                output={},
                scores={"other": 1.0},
                metadata={"scorer_errors": {"acc": "Traceback: scorer failed"}},
            ),
        ],
    )

    translated = BraintrustEngine()._translate(result)

    assert [r.scores for r in translated.results] == [{"acc": 1.0}, {"acc": None}, {}, {"other": 1.0}]
    assert translated.results[2].error == "infra boom"
    assert translated.results[0].error is None
    assert translated.results[3].error == "Scorer errors: acc"
    assert translated.results[3].error_kind == "scorer"
    assert {stats.name: stats.mean for stats in trial_stats(translated.results, trials=1)} == {"acc": 1.0, "other": 1.0}
    assert translated.results[0].input == {"name": "a"}
    assert translated.results[0].expected == {"e": 1}
    assert translated.results[0].metadata == {"m": 1}
    assert translated.summary.engine_name == "braintrust"
    assert translated.summary.experiment_url == "https://bt.example/e"
    assert translated.summary.scores["acc"].score == 0.5


@pytest.mark.asyncio
@pytest.mark.parametrize("has_key", [False, True])
@pytest.mark.parametrize("scorer_fails", [False, True])
async def test_local_results_keep_final_scoring_durations_without_uploading(
    monkeypatch: pytest.MonkeyPatch, has_key: bool, scorer_fails: bool
) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    if has_key:
        monkeypatch.setenv("BRAINTRUST_API_KEY", "test-only-key")
    remote = MagicMock(side_effect=AssertionError("Braintrust reporting must never initialize"))
    monkeypatch.setattr(bt_framework, "init_experiment", remote)
    trials = 0

    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        nonlocal trials
        hooks.metadata["trial_id"] = f"trial-{trials}"
        trials += 1
        hooks.metadata["phase_durations"] = {"agent": 2.0}
        return {}

    async def score(output: Any) -> float:
        if scorer_fails:
            raise ValueError("scorer failed")
        return 1.0

    async def on_results(result: ExperimentResult) -> None:
        for case in result.results:
            assert (case.error is not None) is scorer_fails
            case.metadata["phase_durations"]["scoring"] = 3.0

    result = await BraintrustEngine().run_experiment(
        ExperimentSpec(
            project_name="example",
            cases=[CaseSpec(input={"name": "case"})],
            task=task,
            scorers=[score],
            trial_count=2,
            metadata={},
            on_results=on_results,
        )
    )
    remote.assert_not_called()
    assert result.summary.experiment_url is None
    assert len(result.results) == 2
    assert {case.metadata["trial_id"] for case in result.results} == {"trial-0", "trial-1"}
    assert all(case.metadata["phase_durations"] == {"agent": 2.0, "scoring": 3.0} for case in result.results)


def test_translate_summary_raw_round_trips_as_json() -> None:
    summary = _summary()
    translated = BraintrustEngine()._translate(EvalResultWithSummary(summary=summary, results=[]))

    # The jsonl export must stay byte-identical to what braintrust would write.
    assert translated.summary.as_json() == summary.as_json()
