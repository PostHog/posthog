from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.lazy_seed import seed_canonical_skills
from products.signals.backend.scout_harness.prompt import SignalScoutRunSummary, build_run_prompt
from products.signals.backend.scout_harness.skill_loader import LoadedSkill, load_skill_for_run
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.tasks.backend.models import SandboxEnvironment, Task, TaskRun
from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext
from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession

logger = logging.getLogger(__name__)

# Reuse the report-research sandbox env. Same posture: full repo on disk, restricted
# network, MCP read scopes injected. Split out later if the agent needs different policy.
SIGNALS_SCOUT_SANDBOX_ENV_NAME = SIGNALS_REPORT_RESEARCH_ENV_NAME


@dataclass(frozen=True)
class RunResult:
    """Outcome of a run-trigger.

    `run_id` / `task_run_id` are None when the trigger was skipped without
    persisting a row (e.g. another run for the same team/skill is still in
    flight). `status` mirrors `TaskRun.Status` values as strings so callers
    don't need to import the tasks model.
    """

    run_id: str | None
    task_run_id: str | None
    status: str | None
    last_message: str | None
    runtime_s: float
    skill_name: str
    skill_version: int
    skip_reason: str | None = None


def run_signals_scout(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    repository: str | None = None,
    verbose: bool = False,
) -> RunResult:
    """Synchronous entrypoint: resolves config, spawns sandbox, persists the run row.

    Wraps the async core for callers that aren't inside an event loop (management
    command, direct script). Temporal activities call `arun_signals_scout` directly.
    """
    return asyncio.run(
        arun_signals_scout(
            team_id=team_id,
            skill_name=skill_name,
            skill_version=skill_version,
            repository=repository,
            verbose=verbose,
        )
    )


async def arun_signals_scout(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    repository: str | None = None,
    verbose: bool = False,
) -> RunResult:
    """Async core. Safe to call from inside a running event loop (Temporal activity)."""
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(team_id)
    config = await database_sync_to_async(_resolve_config, thread_sensitive=False)(team)
    # Lazy-seed canonical signals-scout-* skills if the team has none yet, so the run
    # has something to load. Failures here should not crash the run — we log and continue
    # with whatever skills the team already has.
    try:
        await database_sync_to_async(seed_canonical_skills, thread_sensitive=False)(team)
    except Exception:
        logger.exception(
            "signals_scout: canonical skill seed failed; continuing with existing team skills",
            extra={"team_id": team_id},
        )
    skill = await database_sync_to_async(load_skill_for_run, thread_sensitive=False)(
        team, skill_name, version=skill_version
    )

    # Skip-if-running guard. Best-effort — there is a race window between this check
    # and the row insert below (a second trigger could land in between), which we
    # accept until a claim/lease primitive lands.
    if await database_sync_to_async(_has_running_run, thread_sensitive=False)(
        team_id=team.parent_team_id or team.id, skill_name=skill.name
    ):
        logger.info(
            "signals_scout: skipping trigger, prior run still in progress",
            extra={"team_id": team_id, "skill_name": skill.name},
        )
        return RunResult(
            run_id=None,
            task_run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name=skill.name,
            skill_version=skill.version,
            skip_reason="prior run still in progress",
        )

    started = time.monotonic()
    # Pre-mint the bridge row's UUID so the prompt can reference it before the row
    # exists. The TaskRun is created inside `MultiTurnSession.start`; the bridge row is
    # inserted via its `on_task_run_created` hook — after the TaskRun exists but before
    # the agent's first turn — so first-turn finding emits can resolve the run by id.
    run_id = uuid7()
    started_at = timezone.now()
    try:
        last_message, task_run_id = await _spawn_and_run(
            team=team,
            config=config,
            run_id=run_id,
            started_at=started_at,
            skill=skill,
            repository=repository,
            verbose=verbose,
        )
        runtime_s = time.monotonic() - started
        return RunResult(
            run_id=str(run_id),
            task_run_id=task_run_id,
            status=TaskRun.Status.COMPLETED.value,
            last_message=last_message,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )
    except Exception:
        runtime_s = time.monotonic() - started
        # Fail safe and silent: the TaskRun MultiTurnSession spans carries the error
        # context (status=FAILED, error_message, full chat log via LLMA). Nothing
        # additional to persist on the bridge row.
        logger.exception(
            "signals_scout: run failed",
            extra={"team_id": team_id, "run_id": str(run_id), "skill_name": skill.name},
        )
        return RunResult(
            run_id=str(run_id),
            task_run_id=None,
            status=TaskRun.Status.FAILED.value,
            last_message=None,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )


async def _spawn_and_run(
    *,
    team: Team,
    config: SignalScoutConfig,
    run_id: Any,
    started_at: Any,
    skill: LoadedSkill,
    repository: str | None,
    verbose: bool,
) -> tuple[str, str]:
    """Spawn the sandbox, create the bridge row before the first turn, run the agent.

    Returns `(last_message, task_run_id)`.
    """
    user_id = await database_sync_to_async(resolve_user_id_for_team, thread_sensitive=False)(team.id)
    sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
        team.id,
        SIGNALS_SCOUT_SANDBOX_ENV_NAME,
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
        # `signals_scout` is the harness's own scope posture: same scope content as
        # `read_only` (project reads + INTERNAL_SCOPES, including
        # `signal_scout_internal:write`) but reports `has_write_scopes=True` so the
        # MCP server doesn't enable read-only-mode tool filtering. Without that
        # opt-out, the MCP layer would categorically strip every tool annotated
        # `readOnlyHint: false` — including the agent's own `remember`, `forget`,
        # and `emit_finding` tools — even though the OAuth token does carry the
        # right scope to call them.
        posthog_mcp_scopes="signals_scout",
    )
    prompt = build_run_prompt(skill, run_id=str(run_id), team_id=team.id, started_at=started_at)
    logger.info(
        "signals_scout: spawning sandbox",
        extra={
            "team_id": team.id,
            "skill_name": skill.name,
            "skill_version": skill.version,
            "skill_id": skill.skill_id,
            "allowed_tools": skill.allowed_tools,
        },
    )

    async def _create_bridge_row(task_run: TaskRun) -> None:
        # Create the bridge row after the TaskRun exists but BEFORE the agent's first
        # turn runs (via MultiTurnSession's on_task_run_created hook). The scout is
        # single-turn and may call `signals-scout-emit-signal` during that first turn;
        # the emit endpoint resolves the run by id, so the row must already exist or
        # first-turn emits 404. Creating it here (not after `start()` returns) also keeps
        # the cross-link queryable mid-run and surviving both success and failure exits.
        await database_sync_to_async(_create_run_row, thread_sensitive=False)(
            run_id=run_id,
            task_run=task_run,
            team=team,
            config=config,
            skill=skill,
        )

    session, result = await MultiTurnSession.start(
        prompt=prompt,
        context=context,
        model=SignalScoutRunSummary,
        step_name=_step_name(skill),
        verbose=verbose,
        origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        on_task_run_created=_create_bridge_row,
    )
    try:
        # Persist the agent's end-of-turn close-out so non-emitting runs leave a
        # discoverable trace for future-run dedupe. Failure paths skip this on
        # purpose — the bridge row keeps its empty default and the linked TaskRun
        # carries the error context.
        await database_sync_to_async(_finalize_run_summary, thread_sensitive=False)(
            run_id=run_id,
            summary=result.summary,
        )
        return result.summary, str(session.task_run.id)
    finally:
        await session.end()


def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _resolve_config(team: Team) -> SignalScoutConfig:
    """Get-or-create the config row keyed on the canonical (parent) team.

    Default is safe (enabled=False). `SignalScoutConfig` is `TeamScopedRootMixin`, so
    `save()` rewrites a child-environment team to its parent — but the *lookup* half of
    `get_or_create` is not canonicalized. A child-team lookup would miss an existing
    parent row and then try to `create` a duplicate `OneToOne(team)` record, raising
    `IntegrityError`. Resolve to the canonical id so the lookup matches the stored row.
    """
    config, _ = SignalScoutConfig.objects.unscoped().get_or_create(team_id=team.parent_team_id or team.id)
    return config


def _has_running_run(*, team_id: int, skill_name: str) -> bool:
    # Locked on (canonical team, skill_name) — different skills for the same team are
    # allowed to fan out, which is the whole point of `runs_per_tick > 1`. Status flows
    # from the linked TaskRun now that SignalScoutRun is just a bridge; treat both QUEUED
    # and IN_PROGRESS as active, since a TaskRun sits in QUEUED before transitioning and a
    # second trigger landing in that window would otherwise slip past the guard. Not keyed
    # on `scout_config_id`: configs are `on_delete=SET_NULL`, so a config delete/recreate
    # mid-run would orphan the FK and silently defeat the dedupe in exactly the
    # config-churn case it should still cover.
    return (
        SignalScoutRun.objects.unscoped()
        .filter(
            team_id=team_id,
            skill_name=skill_name,
            task_run__status__in=(TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS),
        )
        .exists()
    )


def _create_run_row(
    *,
    run_id: Any,
    task_run: TaskRun,
    team: Team,
    config: SignalScoutConfig,
    skill: LoadedSkill,
) -> SignalScoutRun:
    return SignalScoutRun.objects.unscoped().create(
        id=run_id,
        task_run=task_run,
        team=team,
        scout_config=config,
        skill_name=skill.name,
        skill_version=skill.version,
    )


def _finalize_run_summary(*, run_id: Any, summary: str) -> None:
    # Targeted UPDATE rather than `.save()` — the row's other fields are untouched
    # by the agent's close-out, and `update()` skips the full model refresh.
    SignalScoutRun.objects.unscoped().filter(id=run_id).update(summary=summary)


def _step_name(skill: LoadedSkill) -> str:
    # Surfaces in the Task title and S3 log prefix. Keep terse — the sandbox truncates.
    safe = skill.name.replace(" ", "_")[:40]
    return f"signals_scout:{safe}"
