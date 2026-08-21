from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock

from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.registry import resolve_engine
from products.posthog_ai.eval_harness.engines.types import NullCaseHooks
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.providers import SandboxProviderStrategy
from products.posthog_ai.eval_harness.workflow import _WorkflowEvalRun


class _Reporter:
    def __init__(self) -> None:
        self.done: list[tuple[str, str]] = []

    async def case_done(self, experiment_name: str, case_name: str, duration_seconds: float, status: str) -> None:
        self.done.append((case_name, status))


class _Provider(SandboxProviderStrategy):
    name = "docker"
    default_max_sandboxes = 1

    def preflight(self) -> None:
        return None

    def settings_overrides(self) -> dict[str, object]:
        return {}


def _context(timeout_seconds: int = 30) -> EvalContext:
    demo_data = MagicMock()
    demo_data.make_context.side_effect = lambda name: MagicMock(team_id=1, user_id=2, case_name=name)
    return EvalContext(
        provider="docker",
        provider_strategy=_Provider(),
        agent_model="gpt-test",
        agent_runtime="codex",
        reasoning_effort="high",
        case_filter=None,
        demo_data=demo_data,
        posthog_client=None,
        sandbox_slots=asyncio.Semaphore(1),
        team_setup_slots=asyncio.Semaphore(1),
        one_shot_slots=asyncio.Semaphore(1),
        reporter=_Reporter(),  # type: ignore[arg-type]
        engine=resolve_engine(),
        per_case_timeout_seconds=timeout_seconds,
        trials=1,
    )


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ctx: EvalContext,
    task: Any,
    *,
    project_name: str | None = None,
) -> _WorkflowEvalRun:
    monkeypatch.setattr("products.posthog_ai.eval_harness.base.build_case_dir", lambda *_: tmp_path)
    monkeypatch.setattr("products.posthog_ai.eval_harness.workflow.reclaim_kernels", AsyncMock())
    return _WorkflowEvalRun(
        experiment_name="signals-research",
        cases=[SandboxedEvalCase(name="case-one", prompt="investigate")],
        scorers=[],
        ctx=ctx,
        is_public=True,
        no_send_logs=False,
        task_fn=task,
        project_name=project_name,
    )


def test_workflow_receives_isolated_context_and_writes_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int, str]] = []

    async def task(case, sandbox_context, ctx, hooks):
        seen.append((case.name, sandbox_context.team_id, ctx.agent_model))
        hooks.metadata["step"] = "research"
        return {"result": "done", "raw_log": '{"notification": {"method": "session/update"}}'}

    ctx = _context()
    run = _run(tmp_path, monkeypatch, ctx, task)
    hooks = NullCaseHooks()
    output = asyncio.run(run._execute_case({"name": "case-one", "prompt": "investigate"}, hooks))

    assert seen == [("case-one", 1, "gpt-test")]
    assert output == {
        "result": "done",
        "raw_log": '{"notification": {"method": "session/update"}}',
        "prompt": "investigate",
    }
    assert hooks.metadata["step"] == "research"
    assert (tmp_path / "case-one.summary.txt").exists()
    assert (tmp_path / "case-one.jsonl").read_text() == output["raw_log"]
    ctx.demo_data.make_context.assert_called_once_with("case-one")  # type: ignore[union-attr]


def test_workflow_timeout_is_scored_as_a_case_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case, sandbox_context, ctx, hooks):
        await asyncio.sleep(30)
        return {}

    ctx = _context(timeout_seconds=1)
    run = _run(tmp_path, monkeypatch, ctx, task)
    output = asyncio.run(run._task({"name": "case-one", "prompt": "investigate"}, NullCaseHooks()))

    assert output == {"timeout": True, "error": "case timeout after 1s"}
    assert ctx.reporter.done == [("case-one", "timeout")]  # type: ignore[attr-defined]


def test_workflow_requires_sandbox_infrastructure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case, sandbox_context, ctx, hooks):
        return {}

    ctx = _context()
    ctx.sandbox_slots = None

    with pytest.raises(RuntimeError, match="needs sandbox infrastructure"):
        _run(tmp_path, monkeypatch, ctx, task)


def test_workflow_can_group_steps_in_one_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def task(case, sandbox_context, ctx, hooks):
        return {}

    run = _run(tmp_path, monkeypatch, _context(), task, project_name="signals-agentic")

    assert run._project_name() == "signals-agentic"
