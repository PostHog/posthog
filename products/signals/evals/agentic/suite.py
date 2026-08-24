from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from typing import Any, TypeVar

from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.types import CaseHooks
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.workflow import WorkflowPublicEval
from products.signals.evals.agentic.datasets import EvalCase
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

CaseT = TypeVar("CaseT", bound=EvalCase)
PromptFn = Callable[[CaseT], str]
SetupFn = Callable[[CustomPromptSandboxContext, CaseT | None], dict[str, Any]]
RunFn = Callable[[CaseT, CustomPromptSandboxContext, EvalContext], Awaitable[dict[str, Any]]]
PROJECT_NAME = "signals-agentic"


def harness_cases(
    cases: Sequence[CaseT],
    prompt: PromptFn[CaseT],
    *,
    setup: SetupFn[CaseT] | None = None,
) -> list[SandboxedEvalCase]:
    return [
        SandboxedEvalCase(
            name=case.case_id,
            prompt=prompt(case),
            expected={"case_id": case.case_id, "target": asdict(case).get("expected")},
            metadata={"step": case.step, "notes": case.notes},
            setup=(lambda context, selected=case: setup(context, selected)) if setup else None,
        )
        for case in cases
    ]


async def run_suite(
    *,
    experiment_name: str,
    cases: Sequence[CaseT],
    prompt: PromptFn[CaseT],
    runner: RunFn[CaseT],
    scorers: Sequence[Any],
    ctx: EvalContext,
    setup: SetupFn[CaseT] | None = None,
) -> None:
    by_name = {case.case_id: case for case in cases}

    async def task(
        case: SandboxedEvalCase,
        sandbox_context: CustomPromptSandboxContext,
        eval_context: EvalContext,
        hooks: CaseHooks,
    ) -> dict[str, Any]:
        typed_case = by_name[case.name]
        hooks.metadata.update(
            {
                "signals_step": typed_case.step,
                "agent_runtime": eval_context.agent_runtime,
                "agent_model": eval_context.agent_model,
                "reasoning_effort": eval_context.reasoning_effort,
            }
        )
        return await runner(typed_case, sandbox_context, eval_context)

    await WorkflowPublicEval(
        experiment_name=experiment_name,
        cases=harness_cases(cases, prompt, setup=setup),
        scorers=scorers,
        task=task,
        ctx=ctx,
        project_name=PROJECT_NAME,
    )
