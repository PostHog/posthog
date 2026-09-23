from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Any, Literal

import pytest
from unittest.mock import AsyncMock, MagicMock

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.posthog_ai.backend.models.assistant import CoreMemory
from products.posthog_ai.eval_harness.base import EvalTaskCancelled, EvalTaskError
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.registry import resolve_engine
from products.posthog_ai.eval_harness.engines.types import NullCaseHooks
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.demo_data import SandboxedDemoData
from products.posthog_ai.eval_harness.harness.django_env import NullDbBlocker
from products.posthog_ai.eval_harness.harness.providers import SandboxProviderStrategy
from products.posthog_ai.eval_harness.scorers import ExitCodeZero
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
    demo_data.make_context.side_effect = lambda name, **kwargs: MagicMock(team_id=1, user_id=2, case_name=name)
    return EvalContext(
        provider="docker",
        provider_strategy=_Provider(),
        agent_model="gpt-test",
        agent_runtime="codex",
        skill_delivery="bundled",
        reasoning_effort="high",
        case_filter=None,
        demo_data=demo_data,
        posthog_client=None,
        posthog_evaluation_client=None,
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
    project_data: Literal["hedgebox", "empty"] = "hedgebox",
    no_send_logs: bool = False,
) -> _WorkflowEvalRun:
    monkeypatch.setattr("products.posthog_ai.eval_harness.base.build_case_dir", lambda *_: tmp_path)
    monkeypatch.setattr("products.posthog_ai.eval_harness.workflow.reclaim_kernels", AsyncMock())
    return _WorkflowEvalRun(
        experiment_name="signals-research",
        cases=[SandboxedEvalCase(name="case-one", prompt="investigate", project_data=project_data)],
        scorers=[],
        ctx=ctx,
        is_public=not no_send_logs,
        no_send_logs=no_send_logs,
        task_fn=task,
        project_name=project_name,
    )


@pytest.mark.parametrize("project_data", ["hedgebox", "empty"])
def test_workflow_receives_isolated_context_and_writes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_data: Literal["hedgebox", "empty"]
) -> None:
    seen: list[tuple[str, int, str]] = []

    async def task(case, sandbox_context, ctx, hooks):
        seen.append((case.name, sandbox_context.team_id, ctx.agent_model))
        hooks.metadata["step"] = "research"
        return {"result": "done", "raw_log": '{"notification": {"method": "session/update"}}'}

    ctx = _context()
    run = _run(tmp_path, monkeypatch, ctx, task, project_data=project_data)
    hooks = NullCaseHooks()
    output = asyncio.run(run._task({"name": "case-one", "prompt": "investigate"}, hooks))

    assert seen == [("case-one", 1, "gpt-test")]
    assert output == {
        "result": "done",
        "raw_log": '{"notification": {"method": "session/update"}}',
        "prompt": "investigate",
    }
    assert hooks.metadata["step"] == "research"
    trial_dir = Path(hooks.metadata["artifact_dir"])
    assert (trial_dir / "case-one.summary.txt").exists()
    assert (trial_dir / "case-one.jsonl").read_text() == output["raw_log"]
    assert json.loads((trial_dir / "output.json").read_text()) == output
    ctx.demo_data.make_context.assert_called_once_with("case-one", project_data=project_data)  # type: ignore[union-attr]


def test_workflow_records_agent_usage_in_output_and_local_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_log = "\n".join(
        [
            '{"notification":{"method":"session/update","params":{"update":{"sessionUpdate":"agent_message","content":{"type":"text","text":"done"}}}}}',
            '{"notification":{"method":"_posthog/usage_update","params":{"used":{"inputTokens":10,"outputTokens":2,"cachedReadTokens":3},"cost":0.04}}}',
            '{"notification":{"result":{"stopReason":"end_turn"}}}',
        ]
    )

    async def task(case, sandbox_context, ctx, hooks):
        return {"raw_log": raw_log}

    run = _run(tmp_path, monkeypatch, _context(), task)
    hooks = NullCaseHooks()
    output = asyncio.run(run._execute_case({"name": "case-one", "prompt": "investigate"}, hooks=hooks))

    assert output["token_usage"] == {
        "inputTokens": 10,
        "outputTokens": 2,
        "cachedReadTokens": 3,
        "cachedWriteTokens": 0,
        "totalTokens": 0,
    }
    assert output["cost_usd"] == 0.04
    summary = (Path(hooks.metadata["artifact_dir"]) / "case-one.summary.txt").read_text()
    assert '"inputTokens": 10' in summary


def test_workflow_timeout_is_scored_as_a_case_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    partial_output = {"artifacts": {"reports": [{"summary": "completed before timeout"}]}}
    seed = {"team_id": 1, "shift_seconds": 3600, "id_map": {"saved-report": "restored-report"}}

    async def task(case, sandbox_context, ctx, hooks):
        assert hooks.metadata["seed"] == seed
        raise TimeoutError from EvalTaskCancelled("cancelled", partial_output)

    ctx = _context(timeout_seconds=1)
    run = _run(tmp_path, monkeypatch, ctx, task)
    case = run.cases_by_name["case-one"]
    assert isinstance(case, SandboxedEvalCase)
    case.setup = lambda _: seed
    hooks = NullCaseHooks()
    output = asyncio.run(run._task({"name": "case-one", "prompt": "investigate"}, hooks))

    assert output == partial_output | {"timeout": True, "error": "case timeout after 1s"}
    assert ctx.reporter.done == [("case-one", "timeout")]  # type: ignore[attr-defined]
    trial_dir = Path(hooks.metadata["artifact_dir"])
    assert json.loads((trial_dir / "output.json").read_text()) == output
    execution = json.loads((trial_dir / "execution.json").read_text())
    assert execution["status"] == "timeout"
    assert execution["metadata"]["seed"] == seed


@pytest.mark.parametrize("error_type", [EvalTaskError, EvalTaskCancelled, asyncio.CancelledError])
def test_workflow_failure_retains_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[EvalTaskError] | type[asyncio.CancelledError]
) -> None:
    partial_output = {"artifacts": {"memory": {"cursor": "saved"}}}
    seed = {"team_id": 1, "shift_seconds": 3600, "id_map": {"saved-report": "restored-report"}}

    async def task(case, sandbox_context, ctx, hooks):
        assert hooks.metadata["seed"] == seed
        if error_type is asyncio.CancelledError:
            raise asyncio.CancelledError("stopped")
        raise error_type("stopped", partial_output)

    ctx = _context()
    run = _run(tmp_path, monkeypatch, ctx, task)
    case = run.cases_by_name["case-one"]
    assert isinstance(case, SandboxedEvalCase)
    case.setup = lambda _: seed
    hooks = NullCaseHooks()
    with pytest.raises(error_type):
        asyncio.run(run._task({"name": "case-one", "prompt": "investigate"}, hooks))

    trial_dir = Path(hooks.metadata["artifact_dir"])
    assert json.loads((trial_dir / "output.json").read_text()) == (
        None if error_type is asyncio.CancelledError else partial_output
    )
    execution = json.loads((trial_dir / "execution.json").read_text())
    assert execution["status"] == "error"
    assert execution["error"] == "stopped"
    assert execution["metadata"]["seed"] == seed
    assert ctx.reporter.done == [("case-one", "error")]  # type: ignore[attr-defined]


def test_private_workflow_retains_each_trial_without_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def task(case, sandbox_context, ctx, hooks):
        nonlocal calls
        calls += 1
        return {"exit_code": 0, "reports": [{"summary": f"finding-{calls}"}], "memory": {"cursor": calls}}

    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    ctx = _context()
    ctx.trials = 2
    trace_client = MagicMock()
    evaluation_client = MagicMock()
    ctx.posthog_client = trace_client
    ctx.posthog_evaluation_client = evaluation_client
    ctx.reporter = MagicMock(case_done=AsyncMock(), experiment_started=AsyncMock(), record_summary=AsyncMock())
    monkeypatch.setattr("products.posthog_ai.eval_harness.workflow.reclaim_kernels", AsyncMock())
    run = _WorkflowEvalRun(
        experiment_name="private-repeats",
        cases=[SandboxedEvalCase(name="case-one", prompt="investigate")],
        scorers=[ExitCodeZero()],
        ctx=ctx,
        is_public=False,
        no_send_logs=True,
        task_fn=task,
        output_dir=tmp_path,
    )
    result = asyncio.run(run.run())

    assert len(result.results) == 2
    assert run.run_log_dir.is_relative_to(tmp_path / "private-repeats")
    assert (tmp_path / "runs.jsonl").exists()
    assert len({case.metadata["trial_id"] for case in result.results}) == 2
    assert {case.output["memory"]["cursor"] for case in result.results} == {1, 2}
    for case in result.results:
        trial_dir = Path(case.metadata["artifact_dir"])
        assert json.loads((trial_dir / "output.json").read_text()) == case.output
        stored = json.loads((trial_dir / "result.json").read_text())
        assert stored["output"] == case.output
        assert stored["metadata"]["trial_id"] == case.metadata["trial_id"]
        assert (trial_dir / "case-one.summary.txt").exists()
    trace_client.capture.assert_not_called()
    evaluation_client.capture.assert_not_called()


def test_workflow_does_not_report_success_when_output_cannot_be_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def task(case, sandbox_context, ctx, hooks):
        return {"result": "done"}

    original_write_text = Path.write_text

    def write_text(path: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if path.name == "output.json":
            raise OSError("storage unavailable")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)
    ctx = _context()
    run = _run(tmp_path, monkeypatch, ctx, task)
    with pytest.raises(OSError, match="storage unavailable"):
        asyncio.run(run._task({"name": "case-one", "prompt": "investigate"}, NullCaseHooks()))
    assert ctx.reporter.done == [("case-one", "error")]  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_empty_project_trials_do_not_inherit_demo_data() -> None:
    factory = SandboxedDemoData(master_team_id=-1, django_db_blocker=NullDbBlocker())
    first = factory.make_context("saved-case", project_data="empty")
    second = factory.make_context("saved-case", project_data="empty")

    assert first.team_id != second.team_id
    assert first.user_id != second.user_id
    teams = list(Team.objects.filter(id__in=[first.team_id, second.team_id]))
    assert len({team.organization_id for team in teams}) == 2
    assert all(not team.is_demo and team.parent_team_id is None for team in teams)
    assert not CoreMemory.objects.filter(team_id__in=[first.team_id, second.team_id]).exists()
    assert not FeatureFlag.objects.filter(team_id__in=[first.team_id, second.team_id]).exists()


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
