from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_harness.lazy_seed import seed_canonical_skills
from products.signals.backend.agent_harness.limits import RunLimits, resolve_limits
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
    limit_overrides: dict[str, Any] | None = None,
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
            limit_overrides=limit_overrides,
            repository=repository,
            verbose=verbose,
        )
    )


async def arun_signals_agent(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    limit_overrides: dict[str, Any] | None = None,
    repository: str | None = None,
    verbose: bool = False,
) -> RunResult:
    """Async core. Safe to call from inside a running event loop (Temporal activity)."""
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(team_id)
    config = await database_sync_to_async(_resolve_config, thread_sensitive=False)(team)
    # Lazy-seed canonical signals-agent-* skills if the team has none yet, so the run
    # has something to load. Failures here should not crash the run — we log and continue
    # with whatever skills the team already has.
    try:
        await database_sync_to_async(seed_canonical_skills, thread_sensitive=False)(team)
    except Exception:
        logger.exception(
            "signals_agent: canonical skill seed failed; continuing with existing team skills",
            extra={"team_id": team_id},
        )
    skill = await database_sync_to_async(load_skill_for_run, thread_sensitive=False)(
        team, skill_name, version=skill_version
    )
    limits = _limits_for_run(config, limit_overrides)

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
        team=team, config=config, skill=skill, limits=limits
    )
    started = time.monotonic()
    try:
        last_message = await _spawn_and_run(
            team=team,
            run=run,
            skill=skill,
            limits=limits,
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
            limits=limits,
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


async def _spawn_and_run(
    *,
    team: Team,
    run: SignalAgentRun,
    skill: LoadedSkill,
    limits: RunLimits,
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
    # Capture the Tasks (Task, TaskRun) IDs the harness span ran inside immediately
    # after session start so the cross-link is queryable mid-run, survives both the
    # success and failure finalize paths, and a partial-tick crash still leaves the
    # row pointing at its sandbox. Powers the `task_url` deep-link on the run
    # serializers and the future LLM-analytics token/cost join.
    await database_sync_to_async(_record_task_linkage, thread_sensitive=False)(
        run_id=str(run.id),
        task_id=str(session.task.id),
        task_run_id=str(session.task_run.id),
    )
    try:
        # Limits are captured on the run row but only `max_runtime_s` is actually
        # enforced (via the sandbox poll-loop timeout). `max_findings` is a soft
        # target the agent self-respects via emit-finding idempotency. Per-tool-call
        # iteration would let us gate further but isn't wired today.
        _ = limits
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


def _create_run_row(
    *,
    team: Team,
    config: SignalAgentConfig,
    skill: LoadedSkill,
    limits: RunLimits,
) -> SignalAgentRun:
    return SignalAgentRun.objects.create(
        team=team,
        agent_config=config,
        skill_name=skill.name,
        skill_version=skill.version,
        status=SignalAgentRun.Status.RUNNING,
        metadata={
            "limits": limits.as_dict(),
            "skill_id": skill.skill_id,
            "allowed_tools": skill.allowed_tools_resolution.as_dict(),
        },
    )


def _finalize_completed(*, run_id: str, summary: str, runtime_s: float) -> None:
    # Count findings on the row at finalize — emits during the run pushed onto
    # `findings` via `signals-agent-runs-findings-create`. Reading once here
    # avoids the caller having to thread the count down through the async path.
    findings_count = _read_findings_count(run_id)
    SignalAgentRun.objects.filter(id=run_id).update(
        status=SignalAgentRun.Status.COMPLETED,
        completed_at=timezone.now(),
        summary=summary,
        run_metrics={"runtime_s": runtime_s, "findings": findings_count},
    )


def _record_task_linkage(*, run_id: str, task_id: str, task_run_id: str) -> None:
    """Persist the Tasks `(Task, TaskRun)` IDs the harness span ran inside.

    Read-modify-write the metadata blob so we don't clobber the keys
    `_create_run_row` set (`limits`, `skill_id`, `allowed_tools`). Two writers
    on the same row would race here, but per-run linkage only ever flows from
    one runner invocation, so a plain RMW is safe in practice.
    """
    existing = SignalAgentRun.objects.filter(id=run_id).values_list("metadata", flat=True).first() or {}
    merged = {**existing, "task_id": task_id, "task_run_id": task_run_id}
    SignalAgentRun.objects.filter(id=run_id).update(metadata=merged)


def _finalize_failed(
    *,
    run_id: str,
    exc: BaseException,
    runtime_s: float,
    limits: RunLimits,
    skill: LoadedSkill,
) -> None:
    findings_count = _read_findings_count(run_id)
    # Read existing metadata so we preserve the Tasks linkage (`task_id` /
    # `task_run_id` written mid-run by `_record_task_linkage`) and any other
    # keys the run accreted while annotating with the failure reason. Writing
    # a fresh dict here would silently drop the deep-link to the sandbox that
    # actually died — exactly the row a debugger needs to land on.
    existing = SignalAgentRun.objects.filter(id=run_id).values_list("metadata", flat=True).first() or {}
    merged = {
        **existing,
        "limits": limits.as_dict(),
        "skill_id": skill.skill_id,
        "allowed_tools": skill.allowed_tools_resolution.as_dict(),
        "error_type": type(exc).__name__,
    }
    SignalAgentRun.objects.filter(id=run_id).update(
        status=SignalAgentRun.Status.FAILED,
        completed_at=timezone.now(),
        summary=f"Run failed: {exc!s}",
        run_metrics={"runtime_s": runtime_s, "findings": findings_count},
        metadata=merged,
    )


def _read_findings_count(run_id: str) -> int:
    findings = SignalAgentRun.objects.filter(id=run_id).values_list("findings", flat=True).first() or []
    return len(findings)


def _limits_for_run(config: SignalAgentConfig, overrides: dict[str, Any] | None) -> RunLimits:
    # Three-level merge: harness defaults < per-team config < caller-provided overrides.
    # Merging at the dict layer (not via two stacked `resolve_limits` calls) keeps a
    # caller's `max_runtime_s=900` override from silently dropping the team's
    # `max_findings=3` config — `resolve_limits` only reads the keys it sees.
    merged: dict[str, Any] = {**(config.limit_overrides or {}), **(overrides or {})}
    return resolve_limits(merged or None)


def _step_name(skill: LoadedSkill) -> str:
    # Surfaces in the Task title and S3 log prefix. Keep terse — the sandbox truncates.
    safe = skill.name.replace(" ", "_")[:40]
    return f"signals_agent:{safe}"
