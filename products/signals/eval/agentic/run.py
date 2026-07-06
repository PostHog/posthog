"""Shared orchestration used by both the management command and the pytest entrypoints.

Keeps "build harness → run suite → report → optionally capture" in one place so the two
entry surfaces stay thin and behave identically.
"""

from __future__ import annotations

import os
import random
import asyncio
import logging
from pathlib import Path

from products.signals.eval.agentic.harness import AgenticEvalHarness
from products.signals.eval.agentic.metrics import capture_suite, print_report
from products.signals.eval.agentic.results import SuiteResult
from products.signals.eval.agentic.runners import RunContext
from products.signals.eval.agentic.suites import load_cases

logger = logging.getLogger(__name__)


def build_judge(*, enabled: bool, team_id: int):
    if not enabled:
        return None
    from products.signals.eval.agentic.judge import build_call_llm_judge  # noqa: PLC0415 — keeps gateway import lazy

    return build_call_llm_judge(team_id=team_id)


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
) -> SuiteResult:
    cases = load_cases(step, mode=mode)
    if case_filter:
        cases = [c for c in cases if case_filter in c.case_id]
        if not cases:
            raise ValueError(f"no {step} cases matched filter {case_filter!r}")
    if sample is not None and sample < len(cases):
        # Deterministic sample so subset runs are reproducible across model/prompt comparisons.
        rng = random.Random(seed)
        cases = sorted(cases, key=lambda c: c.case_id)
        rng.shuffle(cases)
        cases = cases[:sample]
    harness = AgenticEvalHarness(
        ctx=RunContext(team_id=team_id, user_id=user_id, cassette_dir=cassette_dir),
        judge=build_judge(enabled=judge_enabled, team_id=team_id),
        concurrency=concurrency,
    )
    return await harness.run_suite(step, cases, mode=mode)


def _capture_client():
    from posthoganalytics import Posthog  # noqa: PLC0415

    return Posthog(
        os.environ.get("POSTHOG_PROJECT_API_KEY", "phx_unused"),
        host=os.environ.get("POSTHOG_HOST", "http://localhost:8010"),
    )


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
) -> dict[str, SuiteResult]:
    """Run one or more steps and print a report; optionally capture results to PostHog."""
    results: dict[str, SuiteResult] = {}
    client = _capture_client() if capture else None
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
            )
        )
        print_report(suite)
        if client is not None:
            capture_suite(client, suite)
        results[step] = suite
    if client is not None:
        client.flush()
    return results
