from __future__ import annotations

import asyncio
from typing import Any

import pytest

from autoevals.score import Score as AutoevalsScore
from braintrust import Score
from braintrust_core.score import Scorer

from products.posthog_ai.eval_harness.engines.braintrust import BraintrustEngine
from products.posthog_ai.eval_harness.engines.types import (
    CaseHooks,
    CaseSpec,
    ExperimentResult,
    ExperimentSpec,
    ScorerResult,
)
from products.posthog_ai.eval_harness.scorers.contract import (
    AsyncOnlyScorerMixin,
    Score as HarnessScore,
    Scorer as HarnessScorer,
)
from products.posthog_ai.eval_harness.scorers.tracing import TracedClients, TracedScorer, _build_posthog_kwargs

# Every ``EvalEngine`` must satisfy these obligations; a future ``PostHogEvalsEngine``
# joins this parameter list and must pass the same suite unchanged.
pytestmark = pytest.mark.parametrize("engine", ["braintrust"], indirect=True)


@pytest.fixture
def engine(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> BraintrustEngine:
    if request.param == "braintrust":
        # Keep the run fully offline: no API key means no login and no network.
        monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
        return BraintrustEngine()
    raise AssertionError(f"unknown engine fixture: {request.param}")


class _MaybeNoneScorer(Scorer):
    """Scores 1.0/0.0 by the ``good`` flag, but skips (``None``) when ``skip`` is set."""

    def _name(self) -> str:
        return "maybe"

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        if output and output.get("skip"):
            return Score(name="maybe", score=None, metadata={"reason": "Does not apply"})
        return Score(name="maybe", score=1.0 if (output and output.get("good")) else 0.0)


def _spec(
    task: Any,
    cases: list[CaseSpec],
    *,
    scorers: list[Any] | None = None,
    trial_count: int = 1,
) -> ExperimentSpec:
    return ExperimentSpec(
        project_name="conformance",
        cases=cases,
        task=task,
        scorers=scorers if scorers is not None else [_MaybeNoneScorer()],
        trial_count=trial_count,
        is_public=False,
        no_send_logs=True,
        metadata={},
    )


def _run(engine: BraintrustEngine, spec: ExperimentSpec) -> ExperimentResult:
    return asyncio.run(engine.run_experiment(spec))


def test_one_result_per_case_and_trial(engine: BraintrustEngine) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {"good": True}

    cases = [CaseSpec(input={"name": name}) for name in ("a", "b", "c")]
    result = _run(engine, _spec(task, cases, trial_count=2))

    assert len(result.results) == 6
    assert [(case.input["name"], case.trial_index) for case in result.results] == [
        (name, index) for name in ("a", "b", "c") for index in (0, 1)
    ]


def test_input_round_trips(engine: BraintrustEngine) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {"good": True}

    cases = [CaseSpec(input={"name": name}) for name in ("a", "b")]
    result = _run(engine, _spec(task, cases))

    assert sorted(r.input["name"] for r in result.results) == ["a", "b"]


def test_hooks_metadata_persisted(engine: BraintrustEngine) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        hooks.metadata["seen"] = input["name"]
        return {"good": True}

    result = _run(engine, _spec(task, [CaseSpec(input={"name": "a"})]))

    assert result.results[0].metadata.get("seen") == "a"


def test_task_exception_becomes_error_and_is_excluded_from_aggregate(engine: BraintrustEngine) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        if input["name"] == "boom":
            raise ValueError("infra boom")
        return {"good": True}

    cases = [CaseSpec(input={"name": name}) for name in ("a", "boom", "b")]
    result = _run(engine, _spec(task, cases))

    by_name = {r.input["name"]: r for r in result.results}
    assert by_name["boom"].error is not None
    assert by_name["boom"].scores == {}
    assert by_name["a"].error is None
    # boom is excluded: the mean is over the two successful 1.0 scores.
    assert result.summary.scores["maybe"].score == 1.0


def test_none_score_preserved_per_case_and_excluded_from_aggregate(engine: BraintrustEngine) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        if input["name"] == "skip":
            return {"skip": True}
        return {"good": input["name"] == "hit"}

    cases = [CaseSpec(input={"name": name}) for name in ("hit", "skip", "miss")]
    result = _run(engine, _spec(task, cases))

    by_name = {r.input["name"]: r for r in result.results}
    assert by_name["skip"].scores == {"maybe": None}
    assert by_name["skip"].scorer_results["maybe"].status == "skipped"
    assert by_name["skip"].scorer_results["maybe"].reasoning == "Does not apply"
    # None is excluded, so the mean is over hit (1.0) and miss (0.0).
    assert result.summary.scores["maybe"].score == 0.5


def test_scorer_details_and_errors_stay_with_concurrent_trials(engine: BraintrustEngine) -> None:
    started = 0
    tasks = 0
    all_started = asyncio.Event()

    class _Judge(AsyncOnlyScorerMixin, HarnessScorer):
        client = object()

        def _name(self) -> str:
            return "judge"

        async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> AutoevalsScore:
            nonlocal started
            started += 1
            if started == 3:
                all_started.set()
            await all_started.wait()
            trace_id = _build_posthog_kwargs()["posthog_trace_id"]
            if output["execution"] == 2:
                raise ValueError("Judge unavailable")
            return AutoevalsScore(
                name="judge",
                score=float(output["execution"]),
                metadata={"rationale": f"Reason {output['execution']}", "observed_trace": trace_id},
            )

    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        nonlocal tasks
        execution = tasks
        tasks += 1
        hooks.metadata["trial_id"] = f"trial-{execution}"
        return {"execution": execution}

    scorer = TracedScorer(
        _Judge(),
        TracedClients(openai_llm_client=object(), anthropic_client=object()),
        {"run_metadata": {}},
        {},
    )
    result = _run(engine, _spec(task, [CaseSpec(input={"name": "same"})], scorers=[scorer], trial_count=3))

    assert tasks == started == 3
    assert result.summary.scores["judge"].score == 0.5
    outcomes = [case.scorer_results["judge"] for case in result.results]
    assert len({outcome.evaluator_trace_id for outcome in outcomes}) == 3
    for case, outcome in zip(result.results, outcomes):
        assert outcome.evaluator_trace_id == case.metadata["scorer_trace_ids"]["judge"]
        assert outcome.evaluated_at is not None and outcome.evaluated_at.tzinfo is not None
        if case.output["execution"] == 2:
            assert outcome.status == "error"
            assert outcome.error_message == "Judge unavailable"
            assert "judge" not in case.scores
        else:
            assert outcome.status == "ok"
            assert outcome.reasoning == f"Reason {case.output['execution']}"
            assert outcome.metadata["observed_trace"] == outcome.evaluator_trace_id
            assert outcome.value == case.scores["judge"]


@pytest.mark.parametrize(
    "outcome",
    [
        ScorerResult(status="ok", value=["relevant"], reasoning="Matches the requested topic", metadata={"rubric": 2}),
        ScorerResult(status="not_applicable", reasoning="No answer to classify"),
    ],
)
def test_explicit_scorer_outcome_keeps_numeric_aggregation_compatible(
    engine: BraintrustEngine, outcome: ScorerResult
) -> None:
    class _ReportingScorer(HarnessScorer):
        def _name(self) -> str:
            return "reporting"

        def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> HarnessScore:
            return HarnessScore("reporting", None, metadata={"source": "classifier"}, result=outcome)

    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {}

    result = _run(engine, _spec(task, [CaseSpec(input={"name": "a"})], scorers=[_ReportingScorer()]))

    actual = result.results[0].scorer_results["reporting"]
    assert actual.status == outcome.status
    assert actual.value == outcome.value
    assert actual.reasoning == outcome.reasoning
    assert actual.metadata == {"source": "classifier", **outcome.metadata}
    assert result.results[0].scores == {"reporting": None}
    assert "reporting" not in result.summary.scores


@pytest.mark.parametrize(
    "score_output, expected_scores",
    [
        (0.5, {"score": 0.5}),
        ({"name": "metric", "score": 0.25, "metadata": {"reason": "Partial match"}}, {"metric": 0.25}),
        ([Score(name="first", score=1.0), Score(name="second", score=None)], {"first": 1.0, "second": None}),
    ],
)
@pytest.mark.parametrize("is_async", [False, True])
def test_callable_scorers_keep_their_supported_return_shapes(
    engine: BraintrustEngine, score_output: object, expected_scores: dict[str, float | None], is_async: bool
) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {"answer": "match"}

    def score(output: dict[str, Any]) -> object:
        assert output == {"answer": "match"}
        return score_output

    async def async_score(output: dict[str, Any]) -> object:
        return score(output)

    scorer = async_score if is_async else score
    expected_scores = {
        "async_score" if name == "score" and is_async else name: value for name, value in expected_scores.items()
    }
    result = _run(engine, _spec(task, [CaseSpec(input={"name": "a"})], scorers=[scorer]))

    assert result.results[0].scores == expected_scores
    assert {name: outcome.value for name, outcome in result.results[0].scorer_results.items()} == expected_scores


def test_engine_does_not_throttle_concurrency(engine: BraintrustEngine) -> None:
    active = 0
    peak = 0

    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return {"good": True}

    cases = [CaseSpec(input={"name": str(i)}) for i in range(5)]
    _run(engine, _spec(task, cases))

    # The engine must admit every case at once; only the harness's own semaphores gate.
    assert peak == 5
