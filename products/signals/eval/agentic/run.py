"""Shared orchestration used by both the management command and the pytest entrypoints.

Keeps "build harness → run suite → report → optionally capture" in one place so the two
entry surfaces stay thin and behave identically.
"""

from __future__ import annotations

import os
import uuid
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from products.signals.eval.agentic.harness import AgenticEvalHarness
from products.signals.eval.agentic.metrics import capture_suite, print_report
from products.signals.eval.agentic.results import SuiteResult
from products.signals.eval.agentic.runners import RunContext
from products.signals.eval.agentic.suites import load_cases

if TYPE_CHECKING:
    from products.signals.backend.agent_runtime import AgentRuntime
    from products.signals.eval.agentic.datasets import EvalCase

logger = logging.getLogger(__name__)


def stable_sample(cases: list[EvalCase], sample: int, seed: int) -> list[EvalCase]:
    """Select by per-case-id hash so adding/removing a case doesn't reshuffle the rest of the subset."""
    return sorted(cases, key=lambda c: hashlib.sha256(f"{seed}:{c.case_id}".encode()).hexdigest())[:sample]


def build_judge(*, enabled: bool, team_id: int, model: str | None = None):
    if not enabled:
        return None
    from products.signals.eval.agentic.judge import build_call_llm_judge  # noqa: PLC0415 — keeps gateway import lazy

    return build_call_llm_judge(team_id=team_id, model=model)


def build_runtime_override(
    *, runtime_adapter: str | None = None, model: str | None = None, reasoning_effort: str | None = None
) -> AgentRuntime | None:
    if not (runtime_adapter or model or reasoning_effort):
        return None
    from products.signals.backend.agent_runtime import AgentRuntime  # noqa: PLC0415

    return AgentRuntime(runtime_adapter=runtime_adapter, model=model, reasoning_effort=reasoning_effort)


async def run_step(
    step: str,
    *,
    mode: str = "replay",
    judge_enabled: bool = False,
    team_id: int = 1,
    user_id: int = 1,
    cassette_dir: Path | None = None,
    case_filter: str | None = None,
    sample: int | None = None,
    seed: int = 1337,
    concurrency: int = 4,
    include_generated: bool | None = None,
    runtime_override: AgentRuntime | None = None,
    judge_model: str | None = None,
) -> SuiteResult:
    # Live/record default to the curated sets — the generated bulk (300+ cases)
    # is for replay breadth, not sandbox runs.
    if include_generated is None:
        include_generated = mode == "replay"
    cases = load_cases(step, mode=mode, include_generated=include_generated)
    if case_filter:
        cases = [c for c in cases if case_filter in c.case_id]
        if not cases:
            raise ValueError(f"no {step} cases matched filter {case_filter!r}")
    if sample is not None and sample < len(cases):
        # Deterministic sample so subset runs are reproducible across model/prompt comparisons.
        cases = stable_sample(cases, sample, seed)
    harness = AgenticEvalHarness(
        ctx=RunContext(
            team_id=team_id,
            user_id=user_id,
            cassette_dir=cassette_dir,
            runtime_override=runtime_override,
        ),
        judge=build_judge(enabled=judge_enabled, team_id=team_id, model=judge_model),
        concurrency=concurrency,
    )
    return await harness.run_suite(step, cases, mode=mode)


def _capture_client():
    from posthoganalytics import Posthog  # noqa: PLC0415

    api_key = os.environ.get("POSTHOG_PROJECT_API_KEY")
    if not api_key:
        # The posthoganalytics consumer swallows delivery failures, so a bogus key would
        # silently drop every event of an expensive run.
        raise RuntimeError("capture requires POSTHOG_PROJECT_API_KEY to be set")
    return Posthog(api_key, host=os.environ.get("POSTHOG_HOST", "http://localhost:8010"))


def run_and_report(
    steps: list[str],
    *,
    mode: str = "replay",
    judge_enabled: bool = False,
    capture: bool = False,
    team_id: int = 1,
    user_id: int = 1,
    cassette_dir: Path | None = None,
    case_filter: str | None = None,
    sample: int | None = None,
    seed: int = 1337,
    concurrency: int = 4,
    include_generated: bool | None = None,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    judge_model: str | None = None,
) -> dict[str, SuiteResult]:
    """Run one or more steps and print a report; optionally capture results to PostHog."""
    results: dict[str, SuiteResult] = {}
    client = _capture_client() if capture else None
    runtime_override = build_runtime_override(
        runtime_adapter=runtime_adapter,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    # One id per invocation so two comparison runs stay distinguishable in report + capture.
    run_id = str(uuid.uuid4())
    for step in steps:
        suite = asyncio.run(
            run_step(
                step,
                mode=mode,
                judge_enabled=judge_enabled,
                team_id=team_id,
                user_id=user_id,
                cassette_dir=cassette_dir,
                case_filter=case_filter,
                sample=sample,
                seed=seed,
                concurrency=concurrency,
                include_generated=include_generated,
                runtime_override=runtime_override,
                judge_model=judge_model,
            )
        )
        print_report(suite, run_id=run_id)
        if client is not None:
            capture_suite(client, suite, run_id=run_id)
        results[step] = suite
    if client is not None:
        client.flush()
    return results
