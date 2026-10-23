from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from unittest.mock import AsyncMock

from autoevals.score import Score as AutoevalsScore
from braintrust import Score
from braintrust_core.score import Scorer
from pydantic import SecretStr

from products.posthog_ai.eval_harness.engines.braintrust import BraintrustEngine
from products.posthog_ai.eval_harness.engines.types import (
    CaseHooks,
    CaseSpec,
    ExperimentResult,
    ExperimentSpec,
    ScorerResult,
)
from products.posthog_ai.eval_harness.offline_results import OfflineEvalPublisher, OfflineEvalSettings, OfflineEvalSuite
from products.posthog_ai.eval_harness.scorers.contract import (
    AsyncOnlyScorerMixin,
    Score as HarnessScore,
    Scorer as HarnessScorer,
)
from products.posthog_ai.eval_harness.scorers.judged import JudgedScorer
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
    record_scorer_results: bool = False,
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
        record_scorer_results=record_scorer_results,
    )


def _run(engine: BraintrustEngine, spec: ExperimentSpec) -> ExperimentResult:
    return asyncio.run(engine.run_experiment(spec))


@pytest.mark.parametrize("record_scorer_results", [False, True])
def test_one_result_per_case_and_trial(engine: BraintrustEngine, record_scorer_results: bool) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {"good": True}

    cases = [CaseSpec(input={"name": name}) for name in ("a", "b", "c")]
    result = _run(engine, _spec(task, cases, trial_count=2, record_scorer_results=record_scorer_results))

    assert len(result.results) == 6
    assert [(case.input["name"], case.trial_index) for case in result.results] == [
        (name, index if record_scorer_results else None) for name in ("a", "b", "c") for index in (0, 1)
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


@pytest.mark.parametrize("record_scorer_results", [False, True])
def test_none_score_preserved_per_case_and_excluded_from_aggregate(
    engine: BraintrustEngine, record_scorer_results: bool
) -> None:
    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        if input["name"] == "skip":
            return {"skip": True}
        return {"good": input["name"] == "hit"}

    cases = [CaseSpec(input={"name": name}) for name in ("hit", "skip", "miss")]
    result = _run(engine, _spec(task, cases, record_scorer_results=record_scorer_results))

    by_name = {r.input["name"]: r for r in result.results}
    assert by_name["skip"].scores == {"maybe": None}
    if record_scorer_results:
        assert by_name["skip"].scorer_results["maybe"].status == "skipped"
        assert by_name["skip"].scorer_results["maybe"].reasoning == "Does not apply"
    else:
        assert all(not case.scorer_results for case in result.results)
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
    result = _run(
        engine,
        _spec(task, [CaseSpec(input={"name": "same"})], scorers=[scorer], trial_count=3, record_scorer_results=True),
    )

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


def test_judge_failure_preserves_zero_aggregate_and_error_upload(
    engine: BraintrustEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Judge(JudgedScorer):
        def _prepare(self, output: Any, expected: Any) -> dict[str, Any]:
            return {"output": output}

    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {"answer": "Synthetic answer"}

    monkeypatch.setattr(
        "autoevals.llm.arun_cached_request", AsyncMock(side_effect=ConnectionError("Judge unavailable"))
    )
    scorer = _Judge(
        name="judge", prompt_template="{{output}}", choice_scores={"yes": 1.0, "no": 0.0}, model="test-model"
    )
    result = _run(engine, _spec(task, [CaseSpec(input={"name": "a"})], scorers=[scorer], record_scorer_results=True))

    case = result.results[0]
    assert case.error is None
    assert case.scores == {"judge": 0.0}
    assert result.summary.scores["judge"].score == 0.0
    outcome = case.scorer_results["judge"]
    assert outcome.status == "error"
    assert outcome.value is None
    assert outcome.error_code == "judge_error"
    assert outcome.error_message == "Judge unavailable"
    assert outcome.evaluated_at is not None

    publisher = OfflineEvalPublisher(
        OfflineEvalSettings(
            project_id=123,
            api_key=SecretStr("test-only-token"),
            scorer_versions={"judge": UUID("00000000-0000-4000-8000-000000000002")},
        ),
        OfflineEvalSuite(
            key="test/judge",
            project_id=123,
            scorer_kinds={"judge": "numeric"},
            scorer_versions={"judge": UUID("00000000-0000-4000-8000-000000000002")},
        ),
    )
    upload = publisher.prepare(
        experiment_id="00000000-0000-4000-8000-000000000001",
        experiment_name="judge-error",
        started_at=outcome.evaluated_at,
        result=result,
        metadata={},
    )
    uploaded = upload.results[0].to_dict()
    assert uploaded["status"] == "error"
    assert "value" not in uploaded
    assert uploaded["error_code"] == "judge_error"
    assert uploaded["payload"]["error_message"] == "Judge unavailable"


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

    result = _run(
        engine, _spec(task, [CaseSpec(input={"name": "a"})], scorers=[_ReportingScorer()], record_scorer_results=True)
    )

    actual = result.results[0].scorer_results["reporting"]
    assert actual.status == outcome.status
    assert actual.value == outcome.value
    assert actual.reasoning == outcome.reasoning
    assert actual.metadata == {"source": "classifier", **outcome.metadata}
    assert result.results[0].scores == {"reporting": None}
    assert "reporting" not in result.summary.scores


@pytest.mark.parametrize(
    "score_output, expected_scores, expected_trace_ids",
    [
        (0.5, {"score": 0.5}, {"score": "origin-trace"}),
        (1.1, {}, {}),
        ([Score(name="first", score=1.0), {"name": "invalid", "score": 0.5}], {}, {}),
        (
            {"name": "metric", "score": 0.25, "metadata": {"reason": "Partial match"}},
            {"metric": 0.25},
            {"metric": "origin-trace"},
        ),
        (
            [
                Score(name="first", score=1.0),
                Score(name="second", score=None),
                HarnessScore(
                    name="third",
                    score=0.25,
                    result=ScorerResult(status="ok", value=0.25, evaluator_trace_id="explicit-trace"),
                ),
            ],
            {"first": 1.0, "second": None, "third": 0.25},
            {"first": "metric-trace", "second": "origin-trace", "third": "explicit-trace"},
        ),
    ],
)
@pytest.mark.parametrize("scorer_form", ["sync", "async", "instance", "class"])
@pytest.mark.parametrize("record_scorer_results", [False, True])
def test_callable_scorers_keep_their_supported_return_shapes(
    engine: BraintrustEngine,
    score_output: object,
    expected_scores: dict[str, float | None],
    expected_trace_ids: dict[str, str],
    scorer_form: str,
    record_scorer_results: bool,
) -> None:
    calls = 0

    async def task(input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        return {"answer": "match"}

    scorer_name = "async_score" if scorer_form == "async" else "score"

    def score(output: dict[str, Any], metadata: dict[str, Any]) -> object:
        nonlocal calls
        calls += 1
        assert output == {"answer": "match"}
        metadata["scorer_trace_ids"] = {
            scorer_name: "origin-trace",
            "first": "metric-trace",
            "third": "metric-trace",
        }
        return score_output

    async def async_score(output: dict[str, Any], metadata: dict[str, Any]) -> object:
        return score(output, metadata)

    class _CallableScorer(Scorer):
        def _name(self) -> str:
            return "score"

        def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Any:
            return score(output, kwargs["metadata"])

    scorer = {"sync": score, "async": async_score, "instance": _CallableScorer(), "class": _CallableScorer}[scorer_form]
    expected_scores = {scorer_name if name == "score" else name: value for name, value in expected_scores.items()}
    expected_trace_ids = {scorer_name if name == "score" else name: value for name, value in expected_trace_ids.items()}
    result = _run(
        engine,
        _spec(task, [CaseSpec(input={"name": "a"})], scorers=[scorer], record_scorer_results=record_scorer_results),
    )

    assert calls == 1
    assert result.results[0].scores == expected_scores
    assert {name: outcome.value for name, outcome in result.results[0].scorer_results.items()} == (
        expected_scores if record_scorer_results else {}
    )
    assert {name: outcome.evaluator_trace_id for name, outcome in result.results[0].scorer_results.items()} == (
        expected_trace_ids if record_scorer_results else {}
    )


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
