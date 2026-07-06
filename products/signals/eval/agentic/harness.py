"""The eval engine: run cases through a step runner and grade the outputs.

The harness is deliberately step-agnostic. It selects the right :class:`StepRunner`,
invokes it under the requested mode, applies the case's scorers, and assembles
:class:`CaseResult` / :class:`SuiteResult`. All step-specific knowledge lives in the
runners and scorers; all aggregation/capture lives in metrics. That separation is what
lets the same engine cover research, repo selection, implementation, and future steps.
"""

from __future__ import annotations

import time
import asyncio
import logging
from typing import Any

from products.signals.eval.agentic.datasets import EvalCase
from products.signals.eval.agentic.results import CaseResult, SuiteResult
from products.signals.eval.agentic.runners import RUNNERS, RunContext, StepRunner
from products.signals.eval.agentic.scoring import JudgeFn, Score, ScoringContext

logger = logging.getLogger(__name__)


class AgenticEvalHarness:
    def __init__(
        self,
        *,
        ctx: RunContext | None = None,
        judge: JudgeFn | None = None,
        concurrency: int = 4,
    ):
        self.ctx = ctx or RunContext()
        self.judge = judge
        self.concurrency = concurrency

    def _runner_for(self, step: str) -> StepRunner:
        if step not in RUNNERS:
            raise KeyError(f"no runner registered for step {step!r}; known: {sorted(RUNNERS)}")
        return RUNNERS[step]

    async def run_case(self, case: EvalCase, *, mode: str) -> CaseResult:
        runner = self._runner_for(case.step)
        result = CaseResult(case_id=case.case_id, step=case.step, mode=mode)
        expected = getattr(case, "expected", None)
        result.expected_repr = str(expected) if expected is not None else ""
        result.input_repr = _safe(runner.input_repr, case)
        started = time.monotonic()
        try:
            output = await runner.run(case, mode=mode, ctx=self.ctx)
        except Exception as exc:  # a step that blew up is a failed case, not a crashed suite
            result.error = f"{type(exc).__name__}: {exc}"
            result.duration_s = time.monotonic() - started
            logger.exception("eval case %s failed to produce output", case.case_id)
            return result
        result.duration_s = time.monotonic() - started
        result.output_repr = _safe(runner.output_repr, output)
        result.scores = await self._score(case, output)
        return result

    async def _score(self, case: EvalCase, output: Any) -> list[Score]:
        sctx = ScoringContext(judge=self.judge, repo_root=self.ctx.cassette_dir and str(self.ctx.cassette_dir))
        scores: list[Score] = []
        for scorer in case.scorers:
            if getattr(scorer, "requires_judge", False) and self.judge is None:
                scores.append(Score(name=scorer.name, value=0.0, passed=False, status="skipped"))
                continue
            try:
                scores.extend(await scorer.score(case, output, sctx))
            except Exception as exc:
                logger.exception("scorer %s raised on case %s", getattr(scorer, "name", scorer), case.case_id)
                scores.append(Score.errored(getattr(scorer, "name", "scorer"), f"{type(exc).__name__}: {exc}"))
        return scores

    async def run_suite(self, step: str, cases: list[EvalCase], *, mode: str) -> SuiteResult:
        # Replay/record swap MultiTurnSession and stub helpers via process-global monkeypatching
        # (the cassette cursor is contextvar-isolated, but the patches are not), so those modes
        # must run one case at a time. Live mode patches nothing global and is the slow path that
        # actually benefits from concurrency, so it honours self.concurrency.
        effective_concurrency = self.concurrency if mode == "live" else 1
        sem = asyncio.Semaphore(effective_concurrency)

        async def _bounded(case: EvalCase) -> CaseResult:
            async with sem:
                return await self.run_case(case, mode=mode)

        case_results = await asyncio.gather(*(_bounded(c) for c in cases))
        # Preserve dataset order for stable reporting.
        order = {c.case_id: i for i, c in enumerate(cases)}
        case_results = sorted(case_results, key=lambda r: order.get(r.case_id, 0))
        return SuiteResult(step=step, mode=mode, cases=list(case_results))


def _safe(fn: Any, arg: Any) -> str:
    try:
        return fn(arg)
    except Exception as exc:  # repr helpers must never sink a run
        return f"<repr error: {type(exc).__name__}: {exc}>"
