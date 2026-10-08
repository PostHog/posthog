from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from threading import Event
from typing import Any, ClassVar

import pytest
from unittest.mock import patch

from django.conf import settings

from posthoganalytics import Posthog

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.engines.registry import resolve_engine
from products.posthog_ai.eval_harness.engines.types import (
    CaseResult,
    EnvVarSpec,
    EvalSummary,
    ExperimentResult,
    ExperimentSpec,
    NullCaseHooks,
)
from products.posthog_ai.eval_harness.harness.cli import parse_args
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.lifecycle import SandboxedEvalHarness
from products.posthog_ai.eval_harness.one_shot import _OneShotEvalRun


class _StubReporter:
    def __init__(self) -> None:
        self.done: list[tuple[str, str]] = []
        self.started: list[tuple[str, int]] = []
        self.summaries: list[tuple[str, Any, int]] = []
        self.posthog_urls: list[tuple[str, str]] = []

    async def case_done(self, experiment_name: str, case_name: str, duration_seconds: float, status: str) -> None:
        self.done.append((case_name, status))

    async def experiment_started(self, experiment_name: str, planned_cases: int, log_dir: Path) -> None:
        self.started.append((experiment_name, planned_cases))

    async def record_summary(self, experiment_name: str, summary: Any, error_count: int) -> None:
        self.summaries.append((experiment_name, summary, error_count))

    async def record_posthog_evaluations_url(self, experiment_name: str, experiment_id: str) -> None:
        self.posthog_urls.append((experiment_name, experiment_id))


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
        posthog_evaluation_client=None,
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


@pytest.mark.parametrize("opt_out_capture", ["", "1"])
@pytest.mark.parametrize("no_send_logs", [False, True])
def test_run_routes_through_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opt_out_capture: str, no_send_logs: bool
) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        raise AssertionError("the engine is stubbed, so the task must not run")

    async def run_suite(run: _OneShotEvalRun) -> None:
        loop = asyncio.get_running_loop()
        loop_progress_during_flush: list[bool] = []

        def blocking_flush() -> None:
            loop_progress = Event()
            loop.call_soon_threadsafe(loop_progress.set)
            loop_progress_during_flush.append(loop_progress.wait(timeout=5))

        with patch.object(Posthog, "flush", side_effect=blocking_flush):
            assert await run.run() is canned
        assert all(loop_progress_during_flush)

    canned = ExperimentResult(
        summary=EvalSummary(engine_name="stub", experiment_name="one-shot-test", scores={}),
        results=[
            CaseResult(
                input={"name": "c1", "prompt": "the prompt"},
                output={"last_message": "done"},
                scores={"correctness": 1.0},
            )
        ],
    )
    monkeypatch.setenv("OPT_OUT_CAPTURE", opt_out_capture)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    engine = _StubEngine(canned)
    harness = SandboxedEvalHarness(parse_args(["--agent-model", "claude-test"]))
    reporter = _StubReporter()

    with (
        patch(
            "posthoganalytics.Posthog", side_effect=partial(Posthog, sync_mode=True, enable_local_evaluation=False)
        ) as create_client,
        patch("posthoganalytics.client.batch_post") as batch_post,
        patch("products.posthog_ai.eval_harness.harness.lifecycle.atexit.register"),
    ):
        with harness._stack:
            harness._bootstrap(frozenset())
            ctx = harness._build_context(frozenset(), reporter)  # type: ignore[arg-type]
            runs = [_build_run(tmp_path, monkeypatch, ctx, task) for _ in range(2)]
            for run in runs:
                run.engine = engine
                run.no_send_logs = no_send_logs
                run.is_public = not no_send_logs
                run.agent_trace_id_lookup["c1"] = "trace-1"
                run.case_trace_meta["c1"] = {"prompt": "the prompt", "duration": 1.0, "first_timestamp": ""}
                asyncio.run(run_suite(run))
            assert settings.TEST
            assert ctx.posthog_client is not None
            assert ctx.posthog_client.disabled
            ctx.posthog_client.capture(event="ordinary_test_event", distinct_id="test")

        assert create_client.call_count == 2
        assert ctx.posthog_evaluation_client is not None
        assert ctx.posthog_evaluation_client.capture(event="$ai_evaluation", distinct_id="after-shutdown") is None

    if no_send_logs:
        batch_post.assert_not_called()
        assert reporter.posthog_urls == []
    else:
        assert batch_post.call_count == 2
        for run, upload_call in zip(runs, batch_post.call_args_list):
            event = upload_call.kwargs["batch"][0]
            assert event["event"] == "$ai_evaluation"
            assert event["properties"]["$ai_metric_name"] == "correctness"
            assert event["properties"]["$ai_score"] == 1.0
            assert event["properties"]["$ai_experiment_id"] == run.experiment_id
        assert reporter.posthog_urls == [("one-shot-test", run.experiment_id) for run in runs]

    assert len(engine.calls) == 2
    for experiment in engine.calls:
        assert experiment.project_name == "one-shot-test"
        assert [case.input["name"] for case in experiment.cases] == ["c1", "c2"]
        assert experiment.metadata == {"agent_model": "claude-test"}
        assert experiment.no_send_logs == no_send_logs
    assert reporter.started == [("one-shot-test", 2)] * 2
    assert reporter.summaries == [("one-shot-test", canned.summary, 0)] * 2
