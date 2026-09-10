from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar

import pytest

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.engines.registry import resolve_engine
from products.posthog_ai.eval_harness.engines.types import (
    EnvVarSpec,
    EvalSummary,
    ExperimentResult,
    ExperimentSpec,
    NullCaseHooks,
)
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.one_shot import _OneShotEvalRun


class _StubReporter:
    def __init__(self) -> None:
        self.done: list[tuple[str, str]] = []
        self.started: list[tuple[str, int]] = []
        self.summaries: list[tuple[str, Any, int]] = []

    async def case_done(self, experiment_name: str, case_name: str, duration_seconds: float, status: str) -> None:
        self.done.append((case_name, status))

    async def experiment_started(self, experiment_name: str, planned_cases: int, log_dir: Path) -> None:
        self.started.append((experiment_name, planned_cases))

    async def record_summary(self, experiment_name: str, summary: Any, error_count: int) -> None:
        self.summaries.append((experiment_name, summary, error_count))


class _StubEngine:
    name: ClassVar[str] = "stub"
    supports_public_experiments: ClassVar[bool] = False

    def __init__(self, result: ExperimentResult) -> None:
        self.result = result
        self.calls: list[ExperimentSpec] = []

    @classmethod
    def required_env(cls) -> tuple[EnvVarSpec, ...]:
        return ()

    async def run_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        self.calls.append(spec)
        return self.result


def _build_ctx(timeout_seconds: int = 30, one_shot_slots: int = 2, case_filter: str | None = None) -> EvalContext:
    return EvalContext(
        provider="docker",
        provider_strategy=None,
        agent_model="claude-test",
        agent_runtime="claude",
        skill_delivery="bundled",
        reasoning_effort=None,
        case_filter=case_filter,
        demo_data=None,
        posthog_client=None,
        sandbox_slots=None,
        team_setup_slots=asyncio.Semaphore(1),
        one_shot_slots=asyncio.Semaphore(one_shot_slots),
        reporter=_StubReporter(),  # type: ignore[arg-type]
        engine=resolve_engine(),
        per_case_timeout_seconds=timeout_seconds,
        trials=1,
    )


def _build_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ctx: EvalContext, task_fn: Any) -> _OneShotEvalRun:
    monkeypatch.setattr("products.posthog_ai.eval_harness.base.build_case_dir", lambda *_: tmp_path)
    return _OneShotEvalRun(
        experiment_name="one-shot-test",
        cases=[BaseEvalCase(name="c1", prompt="the prompt"), BaseEvalCase(name="c2", prompt="other")],
        scorers=[],
        ctx=ctx,
        is_public=False,
        no_send_logs=True,
        task_fn=task_fn,
    )


def test_execute_case_backfills_prompt_and_writes_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        return {"answer": 42, "last_message": "done"}

    ctx = _build_ctx()
    run = _build_run(tmp_path, monkeypatch, ctx, task)
    output = asyncio.run(run._execute_case({"name": "c1", "prompt": "the prompt"}, hooks=NullCaseHooks()))

    assert output["answer"] == 42
    assert output["prompt"] == "the prompt"
    assert (tmp_path / "c1.summary.txt").exists()


def test_task_scores_timeout_as_output_not_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {}

    ctx = _build_ctx(timeout_seconds=1)
    run = _build_run(tmp_path, monkeypatch, ctx, task)
    output = asyncio.run(run._task({"name": "c1", "prompt": "the prompt"}, hooks=NullCaseHooks()))

    assert output == {"timeout": True, "error": "case timeout after 1s"}
    assert ctx.reporter.done == [("c1", "timeout")]  # type: ignore[attr-defined]


def test_task_reraises_infra_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        raise ValueError("boom")

    ctx = _build_ctx()
    run = _build_run(tmp_path, monkeypatch, ctx, task)
    with pytest.raises(ValueError):
        asyncio.run(run._task({"name": "c1", "prompt": "the prompt"}, hooks=NullCaseHooks()))
    assert ctx.reporter.done == [("c1", "error")]  # type: ignore[attr-defined]


def test_one_shot_slots_bound_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active = 0
    max_active = 0

    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {}

    ctx = _build_ctx(one_shot_slots=1)
    run = _build_run(tmp_path, monkeypatch, ctx, task)

    async def run_both() -> None:
        await asyncio.gather(
            run._execute_case({"name": "c1", "prompt": "the prompt"}, hooks=NullCaseHooks()),
            run._execute_case({"name": "c2", "prompt": "other"}, hooks=NullCaseHooks()),
        )

    asyncio.run(run_both())
    assert max_active == 1


def test_case_filter_narrows_eval_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        return {}

    run = _build_run(tmp_path, monkeypatch, _build_ctx(case_filter="c2"), task)
    assert [case.input["name"] for case in run._build_eval_cases()] == ["c2"]


def test_run_routes_through_the_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        raise AssertionError("the engine is stubbed, so the task must not run")

    canned = ExperimentResult(
        summary=EvalSummary(engine_name="stub", experiment_name="one-shot-test", scores={}),
        results=[],
    )
    engine = _StubEngine(canned)
    ctx = _build_ctx()
    run = _build_run(tmp_path, monkeypatch, ctx, task)
    run.engine = engine

    returned = asyncio.run(run.run())

    assert returned is canned
    assert len(engine.calls) == 1
    call = engine.calls[0]
    assert call.project_name == "one-shot-test"
    assert [case.input["name"] for case in call.cases] == ["c1", "c2"]
    assert call.metadata == {"agent_model": "claude-test"}
    reporter = ctx.reporter
    assert reporter.started == [("one-shot-test", 2)]  # type: ignore[attr-defined]
    assert reporter.summaries == [("one-shot-test", canned.summary, 0)]  # type: ignore[attr-defined]
