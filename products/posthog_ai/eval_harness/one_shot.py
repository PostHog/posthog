"""One-shot eval runner: one in-process model invocation per case, no sandbox.

``OneShotEval`` mirrors ``SandboxedEval`` but the per-case work is a
suite-supplied task function instead of a sandboxed agent run. The task
returns the scorer ``output`` dict directly, so each suite defines its own
output shape and its scorers read the keys they know about.
"""

from __future__ import annotations

import json
import time
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

from .base import _BaseEvalRun
from .config import BaseEvalCase
from .engines.types import CaseHooks, ExperimentResult
from .log_sink import write_case_logs

if TYPE_CHECKING:
    from .harness.context import EvalContext

logger = logging.getLogger(__name__)

OneShotTaskFn = Callable[[BaseEvalCase, "EvalContext"], Awaitable[dict[str, Any]]]
"""The per-case task: one model invocation returning the scorer ``output`` dict.

The returned dict must be JSON-serializable (it round-trips through Braintrust).
``prompt`` is backfilled by the runner; an optional ``last_message`` feeds the
local ``.summary.txt``.
"""


class _OneShotEvalRun(_BaseEvalRun):
    """The one-shot incarnation of ``_BaseEvalRun``: a concurrency slot, a
    timeout budget, and local log writing around the suite's task function."""

    trace_namespace = "one-shot"

    def __init__(
        self,
        experiment_name: str,
        cases: Sequence[BaseEvalCase],
        scorers: Sequence[Any],
        ctx: EvalContext,
        is_public: bool,
        no_send_logs: bool,
        task_fn: OneShotTaskFn,
    ) -> None:
        super().__init__(
            experiment_name=experiment_name,
            cases=cases,
            scorers=scorers,
            ctx=ctx,
            is_public=is_public,
            no_send_logs=no_send_logs,
        )
        self._task_fn = task_fn

    async def _execute_case(self, input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        # Re-bind the original case object: it carries what Braintrust's JSON
        # round-trip drops, and the task fn may want `expected`/`metadata`.
        case = self.cases_by_name.get(input["name"]) or BaseEvalCase(name=input["name"], prompt=input.get("prompt", ""))
        started = time.monotonic()
        async with self.ctx.one_shot_slots:
            # Budget the task from slot acquisition, so time spent queued on the
            # semaphore can never eat into a case's timeout.
            output = await asyncio.wait_for(
                self._task_fn(case, self.ctx),
                timeout=self.ctx.per_case_timeout_seconds,
            )
        output.setdefault("prompt", case.prompt)
        await self._write_local_logs(case, output, duration=time.monotonic() - started)
        return output

    async def _write_local_logs(self, case: BaseEvalCase, output: dict[str, Any], duration: float) -> None:
        try:
            write_case_logs(
                case_dir=self.run_log_dir,
                case_name=case.name,
                raw_log=json.dumps(output, indent=2, default=str),
                artifacts={},
                prompt=case.prompt,
                duration=duration,
                last_message=str(output.get("last_message", "")),
            )
        except Exception:
            logger.exception("Failed to write local eval logs for '%s'", case.name)

    def _timeout_output(self) -> dict[str, Any]:
        return {"timeout": True, "error": f"case timeout after {self.ctx.per_case_timeout_seconds}s"}


async def OneShotEval(
    experiment_name: str,
    cases: Sequence[BaseEvalCase],
    scorers: Sequence[Any],
    task: OneShotTaskFn,
    ctx: EvalContext,
    is_public: bool = False,
    no_send_logs: bool = True,
) -> ExperimentResult:
    """Run a one-shot evaluation suite via Braintrust.

    For each ``BaseEvalCase``, invokes ``task(case, ctx)`` once under the global
    ``ctx.one_shot_slots`` limiter with the per-case timeout, then feeds the
    returned dict to the scorers. The suite's module must declare
    ``SUITE_KIND = SuiteKind.ONE_SHOT`` so the harness skips sandbox
    infrastructure for it.
    """
    run = _OneShotEvalRun(
        experiment_name=experiment_name,
        cases=cases,
        scorers=scorers,
        ctx=ctx,
        is_public=is_public,
        no_send_logs=no_send_logs,
        task_fn=task,
    )
    return await run.run()


OneShotPublicEval = partial(OneShotEval, is_public=True, no_send_logs=False)
"""One-shot evaluation whose Braintrust experiment is publicly accessible."""

OneShotPrivateEval = partial(OneShotEval, is_public=False, no_send_logs=True)
"""One-shot evaluation that is not accessible publicly; local logs are the record."""
