from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from posthog.models.team.team import Team

from products.signals.backend.agent_harness.budgets import BudgetCaps, resolve_budget
from products.signals.backend.agent_harness.prompt import build_run_prompt
from products.signals.backend.agent_harness.skill_loader import LoadedSkill, load_skill_for_run
from products.signals.backend.models import SignalAgentConfig, SignalAgentRun
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.tasks.backend.models import SandboxEnvironment, Task
from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, run_prompt

logger = logging.getLogger(__name__)

# Reuse the report-research sandbox env. Same posture: full repo on disk, restricted
# network, MCP read scopes injected. Split out later if the agent needs different policy.
SIGNALS_AGENT_SANDBOX_ENV_NAME = SIGNALS_REPORT_RESEARCH_ENV_NAME


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: SignalAgentRun.Status
    last_message: str | None
    runtime_s: float
    skill_name: str
    skill_version: int


def run_signals_agent(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    budget_overrides: dict[str, Any] | None = None,
    repository: str | None = None,
    verbose: bool = False,
) -> RunResult:
    """Synchronous entrypoint: resolve config, spawn sandbox, persist the run row.

    Hand-trigger surface for the management command and tests. The Temporal scheduler
    will call into the same orchestration once it lands.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    config = _resolve_config(team)
    skill = load_skill_for_run(team, skill_name, version=skill_version)
    budget = _budget_for_run(config, budget_overrides)

    run = SignalAgentRun.objects.create(
        team=team,
        agent_config=config,
        skill_name=skill.name,
        skill_version=skill.version,
        status=SignalAgentRun.Status.RUNNING,
        metadata={"budget": budget.as_dict(), "skill_id": skill.skill_id},
    )

    started = time.monotonic()
    try:
        last_message = asyncio.run(
            _spawn_and_run(
                team=team,
                skill=skill,
                budget=budget,
                repository=repository,
                verbose=verbose,
            )
        )
        runtime_s = time.monotonic() - started
        SignalAgentRun.objects.filter(id=run.id).update(
            status=SignalAgentRun.Status.COMPLETED,
            completed_at=timezone.now(),
            summary=last_message or "",
            budget_used={"runtime_s": runtime_s},
        )
        return RunResult(
            run_id=str(run.id),
            status=SignalAgentRun.Status.COMPLETED,
            last_message=last_message,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )
    except Exception as exc:
        runtime_s = time.monotonic() - started
        # Fail safe and silent: persist the failure on the run row, do not retry blindly.
        logger.exception(
            "signals_agent: run failed",
            extra={"team_id": team_id, "run_id": str(run.id), "skill_name": skill.name},
        )
        SignalAgentRun.objects.filter(id=run.id).update(
            status=SignalAgentRun.Status.FAILED,
            completed_at=timezone.now(),
            summary=f"Run failed: {exc!s}",
            budget_used={"runtime_s": runtime_s},
            metadata={
                "budget": budget.as_dict(),
                "skill_id": skill.skill_id,
                "error_type": type(exc).__name__,
            },
        )
        return RunResult(
            run_id=str(run.id),
            status=SignalAgentRun.Status.FAILED,
            last_message=None,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )


async def _spawn_and_run(
    *,
    team: Team,
    skill: LoadedSkill,
    budget: BudgetCaps,
    repository: str | None,
    verbose: bool,
) -> str:
    user_id = await asyncio.to_thread(resolve_user_id_for_team, team.id)
    sandbox_env_id = await asyncio.to_thread(
        get_or_create_signals_sandbox_env,
        team.id,
        SIGNALS_AGENT_SANDBOX_ENV_NAME,
        SandboxEnvironment.NetworkAccessLevel.TRUSTED,
    )
    context = CustomPromptSandboxContext(
        team_id=team.id,
        user_id=user_id,
        repository=repository,
        sandbox_environment_id=sandbox_env_id,
        posthog_mcp_scopes="read_only",
    )
    prompt = build_run_prompt(skill)
    logger.info(
        "signals_agent: spawning sandbox",
        extra={"team_id": team.id, "skill_name": skill.name, "skill_version": skill.version},
    )
    last_message, _full_log = await run_prompt(
        prompt,
        context,
        step_name=_step_name(skill),
        origin_product=Task.OriginProduct.SIGNALS_AGENT.value,
        verbose=verbose,
    )
    # Budget is captured on the run row but not enforced in Phase 2 — the spawn path is
    # one-shot, the budget will gate per-tool-call iteration once Phase 3 lands.
    _ = budget
    return last_message


def _resolve_config(team: Team) -> SignalAgentConfig:
    """Get-or-create the config row. Defaults are safe (enabled=False, shadow_mode=True)."""
    config, _ = SignalAgentConfig.objects.get_or_create(team=team)
    return config


def _budget_for_run(config: SignalAgentConfig, overrides: dict[str, Any] | None) -> BudgetCaps:
    # Caller-provided overrides win over the config row, which wins over harness defaults.
    if overrides:
        return resolve_budget(overrides)
    return resolve_budget(config.budget_overrides or None)


def _step_name(skill: LoadedSkill) -> str:
    # Surfaces in the Task title and S3 log prefix. Keep terse — the sandbox truncates.
    safe = skill.name.replace(" ", "_")[:40]
    return f"signals_agent:{safe}"
