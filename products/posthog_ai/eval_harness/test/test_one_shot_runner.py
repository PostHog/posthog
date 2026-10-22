from __future__ import annotations

import json
import asyncio
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from threading import Event
from typing import Any, ClassVar

import pytest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

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
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter
from products.posthog_ai.eval_harness.harness.trial_stats import ScorerTrialStats
from products.posthog_ai.eval_harness.one_shot import _OneShotEvalRun
from products.tasks.backend.facade.agents import TurnPollTimeout


class _StubReporter:
    def __init__(self) -> None:
        self.done: list[tuple[str, str]] = []
        self.started: list[tuple[str, int]] = []
        self.summaries: list[tuple[str, Any, int]] = []

    async def case_started(self, experiment: str, name: str, trial_id: str, trial_index: int) -> dict[str, float]:
        return {}

    async def case_phase(self, trial_id: str, phase: str) -> None:
        pass

    async def case_scored(self, trial_id: str, *, error: str | None = None) -> None:
        pass

    async def finish_cases(self, trial_ids: Sequence[str]) -> None:
        pass

    async def finish_experiment(self, experiment: str) -> None:
        pass

    async def case_done(
        self,
        experiment_name: str,
        case_name: str,
        duration_seconds: float,
        status: str,
        trial_id: str | None = None,
        error_type: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        self.done.append((case_name, status))

    async def experiment_started(
        self, experiment_name: str, planned_cases: int, log_dir: Path, *, case_names: Sequence[str] = ()
    ) -> None:
        self.started.append((experiment_name, planned_cases))

    async def record_summary(
        self,
        experiment_name: str,
        summary: Any,
        error_count: int,
        trial_stats: Sequence[ScorerTrialStats] = (),
        case_results: Sequence[Any] = (),
    ) -> None:
        self.summaries.append((experiment_name, summary, error_count))


class _StubEngine:
    name: ClassVar[str] = "stub"
    supports_public_experiments: ClassVar[bool] = False

    def __init__(self, result: ExperimentResult) -> None:
        self.result = result
        self.calls: list[ExperimentSpec] = []

    @classmethod
    def required_env(cls, *, no_send_logs: bool = False) -> tuple[EnvVarSpec, ...]:
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
        git_sha=None,
        git_dirty=None,
    )


def _build_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ctx: EvalContext, task_fn: Any, case_name: str = "c1"
) -> _OneShotEvalRun:
    monkeypatch.setattr("products.posthog_ai.eval_harness.base.build_case_dir", lambda *_: tmp_path)
    return _OneShotEvalRun(
        experiment_name="one-shot-test",
        cases=[BaseEvalCase(name=case_name, prompt="the prompt"), BaseEvalCase(name="c2", prompt="other")],
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


@pytest.mark.parametrize("poll_timeout", [False, True, "cleanup_cancelled"])
def test_task_scores_timeout_as_output_not_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poll_timeout: bool | str
) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        if poll_timeout:
            error = TurnPollTimeout(
                "Poll budget expired",
                stage="no_turn_output",
                elapsed=5,
                stale_seconds=5,
                total_lines=0,
                turn_relevant_lines=0,
            )
            if poll_timeout == "cleanup_cancelled":
                hooks.metadata["poll_timeout"] = error.diagnostics()
                raise TimeoutError
            raise error
        await asyncio.Event().wait()
        return {}

    ctx = _build_ctx(timeout_seconds=1)
    run = _build_run(tmp_path, monkeypatch, ctx, task)
    hooks = NullCaseHooks()
    output = asyncio.run(run._task({"name": "c1", "prompt": "the prompt"}, hooks=hooks))

    assert output is not None and output["timeout"] is True
    assert output["error"] == "case timeout after 1s"
    saved = json.loads((tmp_path / f"c1.trial-{hooks.metadata['trial_id']}.artifacts.json").read_text())
    assert saved == output
    if poll_timeout:
        assert hooks.metadata["poll_timeout"]["poll_timeout_stage"] == "no_turn_output"
        assert output["poll_timeout"] == hooks.metadata["poll_timeout"]
        if poll_timeout is True:
            assert output["stderr"] == "Poll budget expired"
    assert ctx.reporter.done == [("c1", "timeout")]  # type: ignore[attr-defined]


@pytest.mark.parametrize("error_type", [ValueError, asyncio.CancelledError])
def test_task_reraises_infra_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException]
) -> None:
    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        raise error_type("boom")

    ctx = _build_ctx()
    run = _build_run(tmp_path, monkeypatch, ctx, task)
    with pytest.raises(error_type):
        asyncio.run(run._task({"name": "c1", "prompt": "the prompt"}, hooks=NullCaseHooks()))
    assert ctx.reporter.done == ([] if error_type is asyncio.CancelledError else [("c1", "error")])  # type: ignore[attr-defined]


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
    reporter = _StubReporter()

    with (
        patch(
            "posthoganalytics.Posthog", side_effect=partial(Posthog, sync_mode=True, enable_local_evaluation=False)
        ) as create_client,
        patch("posthoganalytics.client.batch_post") as batch_post,
        patch("products.posthog_ai.eval_harness.harness.lifecycle.atexit.register"),
        patch(
            "products.posthog_ai.eval_harness.harness.lifecycle._git",
            side_effect=lambda *args: "abc123" if args[0] == "rev-parse" else "",
        ),
    ):
        harness = SandboxedEvalHarness(parse_args(["--agent-model", "claude-test"]))
        with override_settings(AI_GATEWAY_REDIS_URL="redis://localhost:6381/5"), harness._stack:
            harness._bootstrap(frozenset(), ProgressReporter(total_suites=0))
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
            assert settings.AI_GATEWAY_REDIS_URL is None
            assert ctx.posthog_client is not None
            assert ctx.posthog_client.disabled
            ctx.posthog_client.capture(event="ordinary_test_event", distinct_id="test")

        assert create_client.call_count == 1

    batch_post.assert_not_called()

    assert len(engine.calls) == 2
    for experiment in engine.calls:
        assert experiment.project_name == "one-shot-test"
        assert [case.input["name"] for case in experiment.cases] == ["c1", "c2"]
        assert experiment.metadata == {
            "agent_model": "claude-test",
            "trials": 1,
            "git_sha": "abc123",
            "git_dirty": False,
        }
        assert experiment.no_send_logs == no_send_logs
    assert reporter.started == [("one-shot-test", 2)] * 2
    assert reporter.summaries == [("one-shot-test", canned.summary, 0)] * 2


@pytest.mark.parametrize("case_name", ["c1", "c1" * 110, "c1" * 200])
def test_concurrent_trials_keep_their_own_logs_and_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str
) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    monkeypatch.setenv("EXPORT_EVAL_RESULTS", "1")
    monkeypatch.chdir(tmp_path)
    started = 0
    all_started = asyncio.Event()
    finished = [asyncio.Event() for _ in range(3)]
    completion_order: list[int] = []

    async def task(case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
        nonlocal started
        index = started
        value = index / 2
        started += 1
        if started == 3:
            all_started.set()
        await all_started.wait()
        if index < 2:
            await finished[index + 1].wait()
        completion_order.append(index)
        finished[index].set()
        return {"answer": value, "last_message": str(value)}

    def score(output: dict[str, Any], **kwargs: Any) -> float:
        return output["answer"]

    ctx = _build_ctx(one_shot_slots=3, case_filter=case_name)
    ctx.trials = 3
    run = _build_run(tmp_path, monkeypatch, ctx, task, case_name=case_name)
    run.active_scorers = [score]
    result = asyncio.run(run.run())

    assert len(result.results) == 3
    assert completion_order == [2, 1, 0]
    assert {row.metadata["trial_index"] for row in result.results} == {0, 1, 2}
    assert len(list(tmp_path.glob("*.summary.txt"))) == 3
    assert len({row.metadata["trial_id"] for row in result.results}) == 3
    assert {row.input["name"] for row in result.results} == {case_name}
    exports = [json.loads(line) for line in (tmp_path / "case_results.jsonl").read_text().splitlines()]
    for row in result.results:
        trial_id = row.metadata["trial_id"]
        summary_path = next(tmp_path.glob(f"*.trial-{trial_id}.summary.txt"))
        prefix = summary_path.with_name(summary_path.name.removesuffix(".summary.txt"))
        assert json.loads(prefix.with_name(prefix.name + ".jsonl").read_text()) == row.output
        assert prefix.with_name(prefix.name + ".artifacts.json").exists()
        summary = summary_path.read_text()
        assert f"case: {case_name}\n" in summary
        assert f"trial_id: {trial_id}" in summary
        assert json.loads(summary.split("=== scores ===\n")[1]) == row.scores
        exported = next(item for item in exports if item["trial_id"] == trial_id)
        assert exported["trial_index"] == row.metadata["trial_index"] == row.output["answer"] * 2
        assert exported["scores"] == row.scores
