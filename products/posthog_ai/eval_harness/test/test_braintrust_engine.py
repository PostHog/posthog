from __future__ import annotations

from typing import Any

from braintrust.framework import EvalResult, EvalResultWithSummary
from braintrust.logger import ExperimentSummary, MetricSummary, ScoreSummary

from products.posthog_ai.eval_harness.engines.braintrust import BraintrustEngine, _BraintrustCaseHooks


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


def test_translate_preserves_aggregate_metrics() -> None:
    result: EvalResultWithSummary = EvalResultWithSummary(
        summary=_summary(
            metrics={
                "prompt_tokens": MetricSummary("prompt_tokens", 13, 1234, "", None, None),
                "cost": MetricSummary("cost", 13, 0.045, "", None, None),
            }
        ),
        results=[],
    )

    translated = BraintrustEngine()._translate(result)

    assert translated.summary.metrics["prompt_tokens"].value == 1234
    assert translated.summary.metrics["cost"].value == 0.045


def test_translate_summary_raw_round_trips_as_json() -> None:
    summary = _summary()
    translated = BraintrustEngine()._translate(EvalResultWithSummary(summary=summary, results=[]))

    # The jsonl export must stay byte-identical to what braintrust would write.
    assert translated.summary.as_json() == summary.as_json()


class _FakeSpan:
    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []
        self.end_time: float | None = None

    def log(self, **kwargs: Any) -> None:
        self.logs.append(kwargs)

    def __enter__(self) -> _FakeSpan:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def end(self, end_time: float | None = None) -> None:
        self.end_time = end_time


class _FakeSpanFactory:
    def __init__(self) -> None:
        self.started: list[tuple[str, dict[str, Any], float | None, _FakeSpan]] = []
        self.logs: list[dict[str, Any]] = []

    def log(self, **kwargs: Any) -> None:
        self.logs.append(kwargs)

    def start_span(self, *, name: str, span_attributes: dict[str, Any], start_time: float | None = None) -> _FakeSpan:
        span = _FakeSpan()
        self.started.append((name, span_attributes, start_time, span))
        return span


class _FakeEvalHooks:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.span = _FakeSpanFactory()


def test_case_hooks_adapter_writes_through_metadata_and_translates_spans() -> None:
    hooks = _FakeEvalHooks()
    adapter = _BraintrustCaseHooks(hooks)  # type: ignore[arg-type]

    adapter.metadata["trace_id"] = "t1"
    # Write-through: mutations must land on the underlying braintrust hooks.
    assert hooks.metadata == {"trace_id": "t1"}

    with adapter.start_span("agent", "llm", start_time=10.0, end_time=12.5) as span:
        span.log(output="hi")

    name, attrs, start_time, started_span = hooks.span.started[0]
    assert (name, attrs, start_time) == ("agent", {"type": "llm"}, 10.0)
    assert started_span.logs == [{"output": "hi"}]
    assert started_span.end_time == 12.5
