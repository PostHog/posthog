"""Eval runner for product workflows that launch sandbox agents internally."""

from __future__ import annotations

import json
import time
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

from products.tasks.backend.facade.agents import CustomPromptSandboxContext

from .acp_log import parse_log
from .base import _BaseEvalRun, get_last_assistant_text, log_conversation_spans, prepare_sandbox_case
from .config import SandboxedEvalCase
from .engines.types import CaseHooks, ExperimentResult
from .harness.kernel_sandboxes import reclaim_kernels
from .log_sink import write_case_logs

if TYPE_CHECKING:
    from .harness.context import EvalContext

logger = logging.getLogger(__name__)

WorkflowTaskFn = Callable[
    [SandboxedEvalCase, CustomPromptSandboxContext, "EvalContext", CaseHooks],
    Awaitable[dict[str, Any]],
]


class _WorkflowEvalRun(_BaseEvalRun):
    trace_namespace = "agent-workflow"

    def __init__(
        self,
        experiment_name: str,
        cases: Sequence[SandboxedEvalCase],
        scorers: Sequence[Any],
        ctx: EvalContext,
        is_public: bool,
        no_send_logs: bool,
        task_fn: WorkflowTaskFn,
        project_name: str | None = None,
    ) -> None:
        super().__init__(
            experiment_name=experiment_name,
            cases=cases,
            scorers=scorers,
            ctx=ctx,
            is_public=is_public,
            no_send_logs=no_send_logs,
        )
        if ctx.provider_strategy is None or ctx.demo_data is None or ctx.sandbox_slots is None:
            raise RuntimeError(
                f"Suite '{experiment_name}' needs sandbox infrastructure that this run didn't boot; "
                "is its module missing the sandboxed SUITE_KIND?"
            )
        self._provider_strategy = ctx.provider_strategy
        self._demo_data = ctx.demo_data
        self._sandbox_slots = ctx.sandbox_slots
        self._task_fn = task_fn
        self._braintrust_project_name = project_name or experiment_name

    def _project_name(self) -> str:
        return self._braintrust_project_name

    async def _execute_case(self, input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        original = self.cases_by_name.get(input["name"])
        case = (
            original
            if isinstance(original, SandboxedEvalCase)
            else SandboxedEvalCase(name=input["name"], prompt=input.get("prompt", ""))
        )
        seed: dict[str, Any] = {}

        async with self._sandbox_slots:
            async with self.ctx.team_setup_slots:
                sandbox_context, seed = await prepare_sandbox_case(self._demo_data, case)

            started = time.monotonic()
            try:
                output = await asyncio.wait_for(
                    self._task_fn(case, sandbox_context, self.ctx, hooks),
                    timeout=self.ctx.per_case_timeout_seconds,
                )
            finally:
                await reclaim_kernels(
                    sandbox_context.team_id,
                    keep=self._provider_strategy.keeps_sandboxes(),
                )

        if not isinstance(output, dict):
            raise TypeError(f"Workflow task for '{case.name}' returned {type(output).__name__}, expected dict")
        output.setdefault("prompt", case.prompt)
        if seed:
            output.setdefault("seed", seed)
        raw_log = output.get("raw_log")
        if isinstance(raw_log, str) and raw_log:
            parsed = parse_log(raw_log, initial_prompt=case.prompt)
            log_conversation_spans(hooks, parsed)
            if last_message := get_last_assistant_text(parsed):
                output.setdefault("last_message", last_message)
        await self._write_local_logs(case, output, time.monotonic() - started)
        return output

    async def _write_local_logs(self, case: SandboxedEvalCase, output: dict[str, Any], duration: float) -> None:
        try:
            write_case_logs(
                case_dir=self.run_log_dir,
                case_name=case.name,
                raw_log=(
                    output["raw_log"]
                    if isinstance(output.get("raw_log"), str)
                    else json.dumps(output, indent=2, default=str)
                ),
                artifacts=output.get("artifacts", {}),
                prompt=case.prompt,
                duration=duration,
                last_message=str(output.get("last_message", "")),
                token_usage=output.get("token_usage"),
            )
        except Exception:
            logger.exception("Failed to write local workflow eval logs for '%s'", case.name)

    def _timeout_output(self) -> dict[str, Any]:
        return {"timeout": True, "error": f"case timeout after {self.ctx.per_case_timeout_seconds}s"}

    def _experiment_metadata(self) -> dict[str, Any]:
        return {
            "workflow": self.experiment_name,
            "agent_model": self.ctx.agent_model,
            "agent_runtime": self.ctx.agent_runtime,
            "reasoning_effort": self.ctx.reasoning_effort,
        }


async def WorkflowEval(
    experiment_name: str,
    cases: Sequence[SandboxedEvalCase],
    scorers: Sequence[Any],
    task: WorkflowTaskFn,
    ctx: EvalContext,
    is_public: bool = False,
    no_send_logs: bool = True,
    project_name: str | None = None,
) -> ExperimentResult:
    run = _WorkflowEvalRun(
        experiment_name=experiment_name,
        cases=cases,
        scorers=scorers,
        ctx=ctx,
        is_public=is_public,
        no_send_logs=no_send_logs,
        task_fn=task,
        project_name=project_name,
    )
    return await run.run()


WorkflowPublicEval = partial(WorkflowEval, is_public=True, no_send_logs=False)
WorkflowPrivateEval = partial(WorkflowEval, is_public=False, no_send_logs=True)
