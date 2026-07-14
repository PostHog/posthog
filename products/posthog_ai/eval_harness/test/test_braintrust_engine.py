from __future__ import annotations

from typing import Any

from braintrust.framework import EvalResult, EvalResultWithSummary
from braintrust.logger import ExperimentSummary, ScoreSummary

from products.posthog_ai.eval_harness.engines.braintrust import BraintrustEngine


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
        ],
    )

    translated = BraintrustEngine()._translate(result)

    assert [r.scores for r in translated.results] == [{"acc": 1.0}, {"acc": None}, {}]
    assert translated.results[2].error == "infra boom"
    assert translated.results[0].error is None
    assert translated.results[0].input == {"name": "a"}
    assert translated.results[0].expected == {"e": 1}
    assert translated.results[0].metadata == {"m": 1}
    assert translated.summary.engine_name == "braintrust"
    assert translated.summary.experiment_url == "https://bt.example/e"
    assert translated.summary.scores["acc"].score == 0.5


def test_translate_summary_raw_round_trips_as_json() -> None:
    summary = _summary()
    translated = BraintrustEngine()._translate(EvalResultWithSummary(summary=summary, results=[]))

    # The jsonl export must stay byte-identical to what braintrust would write.
    assert translated.summary.as_json() == summary.as_json()
