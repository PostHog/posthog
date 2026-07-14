from __future__ import annotations

import asyncio
from dataclasses import dataclass

from posthoganalytics import Posthog

from ..engines.base import EvalEngine
from .cli import SkillDelivery
from .demo_data import SandboxedDemoData
from .providers import SandboxProvider, SandboxProviderStrategy
from .reporting import ProgressReporter


@dataclass
class EvalContext:
    """Everything a suite function needs, assembled once per harness run.

    Replaces the pytest fixtures (``sandboxed_demo_data``, ``pytestconfig``,
    ``posthog_client``) that suites used to take individually. Passed unchanged
    down into ``SandboxedEval`` / ``OneShotEval``.

    Infra-backed fields are ``None`` when the run's suite kinds didn't require
    that infrastructure to boot; the runners narrow them and fail loudly if a
    suite's ``SUITE_KIND`` under-declares what it uses.
    """

    provider: SandboxProvider
    """Provider label, kept for display and metadata only."""

    provider_strategy: SandboxProviderStrategy | None
    """The live provider strategy — the behavior hook for per-case teardown.
    ``None`` when no selected suite is sandboxed."""

    agent_model: str
    """Model every agent or one-shot generation runs against. Pinned for stable
    comparisons."""

    agent_runtime: str
    """Runtime adapter serving the sandboxed agent's model (``"claude"`` | ``"codex"``)."""

    skill_delivery: SkillDelivery
    """Whether the run uses native bundled skills or MCP exec distribution."""

    reasoning_effort: str | None
    """Agent reasoning effort override; ``None`` keeps the agent server's default."""

    case_filter: str | None
    """Substring filter on case names, from ``--eval``."""

    demo_data: SandboxedDemoData | None
    """Master Hedgebox seed plus the per-case isolated team factory. ``None``
    when no selected suite requires demo data."""

    posthog_client: Posthog | None
    """Analytics client for eval trace + evaluation event capture."""

    sandbox_slots: asyncio.Semaphore | None
    """The one global limiter on concurrently live sandboxes, shared by every
    suite. ``None`` when no selected suite is sandboxed."""

    team_setup_slots: asyncio.Semaphore
    """Bounds concurrent team cloning and case seeders to protect ClickHouse RAM."""

    one_shot_slots: asyncio.Semaphore
    """The one global limiter on concurrently running one-shot cases, shared by
    every suite — the one-shot analog of ``sandbox_slots``."""

    reporter: ProgressReporter
    """Owns all terminal output and the ``eval_results.jsonl`` export."""

    engine: EvalEngine
    """The execution/reporting backend every suite runs on, resolved once per run."""

    per_case_timeout_seconds: int
    """Budget for the agent run, started after team setup so queueing cannot consume it."""

    trials: int
    """Times each case runs. Agents are stochastic, so N runs per case measure
    the variance a single run can't reveal."""
