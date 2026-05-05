from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_harness.budgets import DEFAULT_MAX_RUNTIME_S, BudgetCaps, resolve_budget
from products.signals.backend.agent_harness.lazy_seed import seed_canonical_skills
from products.signals.backend.agent_harness.prompt import SignalAgentRunSummary, build_run_prompt
from products.signals.backend.agent_harness.skill_loader import LoadedSkill, load_skill_for_run
from products.signals.backend.models import SignalAgentConfig, SignalAgentRun
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.tasks.backend.models import SandboxEnvironment, Task
from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext
from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession

logger = logging.getLogger(__name__)

# Reuse the report-research sandbox env. Same posture: full repo on disk, restricted
# network, MCP read scopes injected. Split out later if the agent needs different policy.
SIGNALS_AGENT_SANDBOX_ENV_NAME = SIGNALS_REPORT_RESEARCH_ENV_NAME


@dataclass(frozen=True)
class RunResult:
    """Outcome of a run-trigger.

    `run_id` and `status` are None when the trigger was skipped without persisting
    a row (e.g. another run for the same team/config is still in flight).
    """

    run_id: str | None
    status: SignalAgentRun.Status | None
    last_message: str | None
    runtime_s: float
    skill_name: str
    skill_version: int
    skip_reason: str | None = None


def run_signals_agent(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    budget_overrides: dict[str, Any] | None = None,
    repository: str | None = None,
    verbose: bool = False,
) -> RunResult:
    """Synchronous entrypoint: resolves config, spawns sandbox, persists the run row.

    Wraps the async core for callers that aren't inside an event loop (management
    command, direct script). Temporal activities call `arun_signals_agent` directly.
    """
    return asyncio.run(
        arun_signals_agent(
            team_id=team_id,
            skill_name=skill_name,
            skill_version=skill_version,
            budget_overrides=budget_overrides,
            repository=repository,
            verbose=verbose,
        )
    )


async def arun_signals_agent(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    budget_overrides: dict[str, Any] | None = None,
    repository: str | None = None,
    verbose: bool = False,
) -> RunResult:
    """Async core. Safe to call from inside a running event loop (Temporal activity)."""
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(team_id)
    config = await database_sync_to_async(_resolve_config, thread_sensitive=False)(team)
    # Lazy-seed canonical signals-agent-* skills before we resolve the skill the run
    # asked for. No-op when the team already has any signals-agent-* row (preserves
    # edits/forks). Failures here should not crash the run — we log and continue.
    try:
        await database_sync_to_async(seed_canonical_skills, thread_sensitive=False)(team)
    except Exception:
        logger.exception(
            "signals_agent: lazy seed failed; continuing with existing team skills",
            extra={"team_id": team_id},
        )
    skill = await database_sync_to_async(load_skill_for_run, thread_sensitive=False)(
        team, skill_name, version=skill_version
    )
    budget = _budget_for_run(config, budget_overrides)

    # Self-heal stale RUNNING rows whose age exceeds 2x their max_runtime_s. Catches
    # rows left behind when a worker / sandbox died before the cleanup path could run
    # (e.g. SIGTERM during file-watcher restart, kernel OOM, asyncio cancellation that
    # escaped the harness). Without this, a single stale row blocks every subsequent
    # coordinator tick from spawning a fresh run.
    await database_sync_to_async(_self_heal_stale_runs, thread_sensitive=False)(team_id, config.id)

    # Skip-if-running guard. Best-effort — there is a TOCTOU window between this check
    # and the row insert below; we accept that until a claim/lease primitive lands.
    if await database_sync_to_async(_has_running_run, thread_sensitive=False)(team_id, config.id):
        logger.info(
            "signals_agent: skipping trigger, prior run still RUNNING",
            extra={"team_id": team_id, "skill_name": skill.name},
        )
        return RunResult(
            run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name=skill.name,
            skill_version=skill.version,
            skip_reason="prior run still in RUNNING status",
        )

    run = await database_sync_to_async(_create_run_row, thread_sensitive=False)(
        team=team, config=config, skill=skill, budget=budget
    )
    started = time.monotonic()
    try:
        last_message = await _spawn_and_run(
            team=team,
            run=run,
            skill=skill,
            budget=budget,
            repository=repository,
            verbose=verbose,
        )
        runtime_s = time.monotonic() - started
        await database_sync_to_async(_finalize_completed, thread_sensitive=False)(
            run_id=run.id, summary=last_message or "", runtime_s=runtime_s
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
        await database_sync_to_async(_finalize_failed, thread_sensitive=False)(
            run_id=run.id,
            exc=exc,
            runtime_s=runtime_s,
            budget=budget,
            skill=skill,
        )
        return RunResult(
            run_id=str(run.id),
            status=SignalAgentRun.Status.FAILED,
            last_message=None,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )
    except BaseException as exc:
        # Cancellation / worker-shutdown / system-exit: persist the failure so the row
        # doesn't go stale, then re-raise so Temporal sees the activity as failed. The
        # `except Exception` branch above doesn't catch `asyncio.CancelledError` (which
        # subclasses BaseException in Python 3.8+) — without this, "Worker is shutting
        # down" leaves the row at status=running and blocks every subsequent run.
        runtime_s = time.monotonic() - started
        logger.warning(
            "signals_agent: run cancelled mid-flight, marking row failed",
            extra={
                "team_id": team_id,
                "run_id": str(run.id),
                "skill_name": skill.name,
                "exception_type": type(exc).__name__,
            },
        )
        try:
            await database_sync_to_async(_finalize_failed, thread_sensitive=False)(
                run_id=run.id,
                exc=exc,
                runtime_s=runtime_s,
                budget=budget,
                skill=skill,
            )
        except Exception:
            # If we can't even write the failure row (e.g. worker truly going away),
            # let the next coordinator tick's self-heal path catch it. Don't swallow
            # the original cancellation.
            logger.exception(
                "signals_agent: failed to mark row failed during cancellation; "
                "self-heal will reconcile on next coordinator tick",
                extra={"team_id": team_id, "run_id": str(run.id)},
            )
        raise


async def _spawn_and_run(
    *,
    team: Team,
    run: SignalAgentRun,
    skill: LoadedSkill,
    budget: BudgetCaps,
    repository: str | None,
    verbose: bool,
) -> str:
    user_id = await database_sync_to_async(resolve_user_id_for_team, thread_sensitive=False)(team.id)
    sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
        team.id,
        SIGNALS_AGENT_SANDBOX_ENV_NAME,
        SandboxEnvironment.NetworkAccessLevel.TRUSTED,
    )
    # `repository` is None on the cadence path — v1 doesn't clone a repo into the
    # sandbox. The kwarg stays wired so the management command can still pass
    # `--repository` for ad-hoc local investigations; productionised repo access
    # is deferred (see implementation plan).
    context = CustomPromptSandboxContext(
        team_id=team.id,
        user_id=user_id,
        repository=repository,
        sandbox_environment_id=sandbox_env_id,
        posthog_mcp_scopes="read_only",
    )
    prompt = build_run_prompt(skill, run_id=str(run.id), team_id=team.id, started_at=run.started_at)
    logger.info(
        "signals_agent: spawning sandbox",
        extra={"team_id": team.id, "skill_name": skill.name, "skill_version": skill.version},
    )
    session, result = await MultiTurnSession.start(
        prompt=prompt,
        context=context,
        model=SignalAgentRunSummary,
        step_name=_step_name(skill),
        verbose=verbose,
        origin_product=Task.OriginProduct.SIGNALS_AGENT,
    )
    try:
        # Budget is captured on the run row but not enforced here — the spawn path is one-shot,
        # so per-tool-call iteration will gate against the budget once the agent-SDK glue lands.
        _ = budget
        return result.summary
    finally:
        await session.end()


def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _resolve_config(team: Team) -> SignalAgentConfig:
    """Get-or-create the config row. Defaults are safe (enabled=False, shadow_mode=True)."""
    config, _ = SignalAgentConfig.objects.get_or_create(team=team)
    return config


def _has_running_run(team_id: int, config_id: str) -> bool:
    return SignalAgentRun.objects.filter(
        team_id=team_id,
        agent_config_id=config_id,
        status=SignalAgentRun.Status.RUNNING,
    ).exists()


# Stale rows past this multiple of their max_runtime_s budget are reconciled to FAILED.
# 2x is conservative: a run that legitimately runs over budget by 2x is so rare that we
# accept the rare false positive in exchange for never blocking fresh runs indefinitely.
_STALE_RUN_MULTIPLIER = 2


def _self_heal_stale_runs(team_id: int, config_id: str) -> None:
    """Reconcile RUNNING rows older than `_STALE_RUN_MULTIPLIER * max_runtime_s` to FAILED.

    Catches rows orphaned by worker shutdown, sandbox crash, or async cancellation that
    bypassed the activity's cleanup path. The row's own recorded `max_runtime_s` budget
    is the staleness threshold base — a row started with a 1800s budget is treated as
    stale after 3600s of wall-clock RUNNING time.

    Idempotent: safe to call from any number of concurrent coordinator activities.
    """
    candidates = SignalAgentRun.objects.filter(
        team_id=team_id,
        agent_config_id=config_id,
        status=SignalAgentRun.Status.RUNNING,
    ).only("id", "started_at", "metadata")
    now = timezone.now()
    for run in candidates:
        budget_max_s = ((run.metadata or {}).get("budget", {}) or {}).get("max_runtime_s") or DEFAULT_MAX_RUNTIME_S
        threshold_s = _STALE_RUN_MULTIPLIER * budget_max_s
        age_s = (now - run.started_at).total_seconds()
        if age_s <= threshold_s:
            continue
        SignalAgentRun.objects.filter(id=run.id, status=SignalAgentRun.Status.RUNNING).update(
            status=SignalAgentRun.Status.FAILED,
            completed_at=now,
            summary=(
                f"Run row auto-healed: status=RUNNING for {age_s:.0f}s "
                f"(threshold {threshold_s}s = {_STALE_RUN_MULTIPLIER}x max_runtime_s). "
                f"Worker / sandbox likely died without the cleanup path running."
            ),
        )
        logger.warning(
            "signals_agent: self-healed stale running run",
            extra={
                "team_id": team_id,
                "run_id": str(run.id),
                "age_s": age_s,
                "threshold_s": threshold_s,
            },
        )


def _create_run_row(
    *,
    team: Team,
    config: SignalAgentConfig,
    skill: LoadedSkill,
    budget: BudgetCaps,
) -> SignalAgentRun:
    return SignalAgentRun.objects.create(
        team=team,
        agent_config=config,
        skill_name=skill.name,
        skill_version=skill.version,
        status=SignalAgentRun.Status.RUNNING,
        metadata={
            "budget": budget.as_dict(),
            "skill_id": skill.skill_id,
            "allowed_tools": skill.allowed_tools_resolution.as_dict(),
        },
    )


def _finalize_completed(*, run_id: str, summary: str, runtime_s: float) -> None:
    SignalAgentRun.objects.filter(id=run_id).update(
        status=SignalAgentRun.Status.COMPLETED,
        completed_at=timezone.now(),
        summary=summary,
        budget_used={"runtime_s": runtime_s},
    )


def _finalize_failed(
    *,
    run_id: str,
    exc: BaseException,
    runtime_s: float,
    budget: BudgetCaps,
    skill: LoadedSkill,
) -> None:
    SignalAgentRun.objects.filter(id=run_id).update(
        status=SignalAgentRun.Status.FAILED,
        completed_at=timezone.now(),
        summary=f"Run failed: {exc!s}",
        budget_used={"runtime_s": runtime_s},
        metadata={
            "budget": budget.as_dict(),
            "skill_id": skill.skill_id,
            "allowed_tools": skill.allowed_tools_resolution.as_dict(),
            "error_type": type(exc).__name__,
        },
    )


def _budget_for_run(config: SignalAgentConfig, overrides: dict[str, Any] | None) -> BudgetCaps:
    # Caller-provided overrides win over the config row, which wins over harness defaults.
    if overrides:
        return resolve_budget(overrides)
    return resolve_budget(config.budget_overrides or None)


def _step_name(skill: LoadedSkill) -> str:
    # Surfaces in the Task title and S3 log prefix. Keep terse — the sandbox truncates.
    safe = skill.name.replace(" ", "_")[:40]
    return f"signals_agent:{safe}"
