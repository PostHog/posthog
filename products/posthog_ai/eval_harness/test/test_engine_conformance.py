from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import pytest

import braintrust.framework as bt_framework
from braintrust import Score
from braintrust.framework import EvalResult, Evaluator
from braintrust.logger import ExperimentSummary, ScoreSummary
from braintrust_core.score import Scorer

from products.posthog_ai.eval_harness.engines.braintrust import BraintrustEngine
from products.posthog_ai.eval_harness.engines.types import CaseHooks, CaseSpec, ExperimentResult, ExperimentSpec

# Every ``EvalEngine`` must satisfy these obligations; a future ``PostHogEvalsEngine``
# joins this parameter list and must pass the same suite unchanged.
pytestmark = pytest.mark.parametrize("engine", ["braintrust"], indirect=True)


def _none_safe_local_summary(
    evaluator: Evaluator[Any, Any], results: Sequence[EvalResult[Any, Any]]
) -> ExperimentSummary:
    """A None-aware replacement for braintrust's offline ``build_local_summary``.

    The stock offline path sums ``None`` scores and crashes (a local-mode bug the
    authenticated path doesn't have — the real harness always runs authenticated).
    This shim excludes ``None`` from the mean, matching authenticated behavior, so
    the offline fixture can exercise the None-exclusion the engine contract promises.
    """
    by_name: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))
    for result in results:
        for name, score in result.scores.items():
            if score is None:
                continue
            total, count = by_name[name]
            by_name[name] = (total + score, count + 1)
    longest = max((len(name) for name in by_name), default=0)
    scores = {
        name: ScoreSummary(
            name=name,
            _longest_score_name=longest,
            score=(total / count if count else 0.0),
            improvements=0,
            regressions=0,
        )
        for name, (total, count) in by_name.items()
    }
    return ExperimentSummary(
        project_name=evaluator.project_name,
        project_id=None,
        experiment_id=None,
        experiment_name=evaluator.experiment_name or evaluator.project_name,
        project_url=None,
        experiment_url=None,
        comparison_experiment_name=None,
        scores=scores,
        metrics={},
    )


@pytest.fixture
def engine(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> BraintrustEngine:
    if request.param == "braintrust":
        # Keep the run fully offline: no API key means no login and no network.
        monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
        monkeypatch.setattr(bt_framework, "build_local_summary", _none_safe_local_summary)
        return BraintrustEngine()
    raise AssertionError(f"unknown engine fixture: {request.param}")


class _MaybeNoneScorer(Scorer):
    """Scores 1.0/0.0 by the ``good`` flag, but skips (``None``) when ``skip`` is set."""

    def _name(self) -> str:
        return "maybe"

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        if output and output.get("skip"):
            return Score(name="maybe", score=None)
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
    # None is excluded, so the mean is over hit (1.0) and miss (0.0).
    assert result.summary.scores["maybe"].score == 0.5


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
