from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

import posthoganalytics

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills
from products.signals.backend.scout_harness.limits import DEFAULT_MAX_RUNTIME_S
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
    # Sync canonical signals-scout-* skills before we resolve the skill the run asked for.
    # Creates rows for newly-shipped specialists, updates harness-seeded rows the team
    # hasn't edited, and leaves forked / tombstoned rows alone. Failures here should not
    # crash the run — we log and continue with whatever skills the team already has.
    try:
        await database_sync_to_async(sync_canonical_skills, thread_sensitive=False)(team)
    except Exception:
        logger.exception(
            "signals_scout: canonical skill sync failed; continuing with existing team skills",
            extra={"team_id": team_id},
        )
    skill = await database_sync_to_async(load_skill_for_run, thread_sensitive=False)(
        team, skill_name, version=skill_version
    )
    config = await database_sync_to_async(_resolve_config, thread_sensitive=False)(team, skill.name)

    # Hook for stale-run recovery — currently a no-op (see `_self_heal_stale_runs`). The
    # partial unique index that made orphaned RUNNING rows block dispatch was dropped when
    # `SignalScoutRun` became a `TaskRun` bridge (status now lives on `task_run.status`), so
    # stale bridge rows no longer gate new runs at the DB level. Kept as a seam for the
    # `task_run.status`-based recovery follow-up.
    await database_sync_to_async(_self_heal_stale_runs, thread_sensitive=False)(team_id, skill_name)

    # Skip-if-running guard, keyed on (team, skill_name). Different skills for the same
    # team are allowed to run concurrently — the coordinator can dispatch several due
    # scouts for one team in a single tick. Best-effort — there is a race window between
    # this check and the bridge-row insert inside _spawn_and_run (a second trigger could
    # land in between), which we accept until a claim/lease primitive lands.
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
        emitted_count, _ = await database_sync_to_async(_read_run_metrics, thread_sensitive=False)(
            run_id, team.parent_team_id or team.id
        )
        _capture_run_finished(
            team=team,
            config=config,
            skill=skill,
            run_id=run_id,
            task_run_id=task_run_id,
            status=TaskRun.Status.COMPLETED.value,
            runtime_s=runtime_s,
            emitted_count=emitted_count,
        )
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
        # A failure before the on_task_run_created hook fires means no row was persisted —
        # don't hand callers a run_id that resolves to nothing.
        row_persisted = await database_sync_to_async(_run_row_exists, thread_sensitive=False)(
            run_id, team.parent_team_id or team.id
        )
        # Fail safe and silent: the TaskRun MultiTurnSession spans carries the error
        # context (status=FAILED, error_message, full chat log via LLMA). Nothing
        # additional to persist on the bridge row.
        logger.exception(
            "signals_scout: run failed",
            extra={
                "team_id": team_id,
                "run_id": str(run_id),
                "skill_name": skill.name,
                "row_persisted": row_persisted,
            },
        )
        # A partial run can still have emitted (and have a linked TaskRun) before failing,
        # so read both from the bridge row when it exists; otherwise it never ran far
        # enough to persist either.
        emitted_count, failed_task_run_id = (
            await database_sync_to_async(_read_run_metrics, thread_sensitive=False)(
                run_id, team.parent_team_id or team.id
            )
            if row_persisted
            else (0, None)
        )
        _capture_run_finished(
            team=team,
            config=config,
            skill=skill,
            run_id=run_id,
            task_run_id=failed_task_run_id,
            status=TaskRun.Status.FAILED.value,
            runtime_s=runtime_s,
            emitted_count=emitted_count,
        )
        return RunResult(
            run_id=str(run_id) if row_persisted else None,
            task_run_id=None,
            status=TaskRun.Status.FAILED.value,
            last_message=None,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )
    except BaseException as exc:
        # Cancellation / worker-shutdown / system-exit: re-raise so Temporal sees the
        # activity as failed. Post-collapse the bridge row's status flows from its
        # linked TaskRun (managed by MultiTurnSession), so we don't update anything
        # here directly. A TaskRun stranded in IN_PROGRESS (e.g. SIGKILL before
        # MultiTurnSession finalizes) blocks new runs for this (team, skill) via
        # `_has_running_run` until it transitions out — active recovery is a deferred
        # follow-up (see `_self_heal_stale_runs`).
        runtime_s = time.monotonic() - started
        logger.warning(
            "signals_scout: run cancelled mid-flight",
            extra={
                "team_id": team_id,
                "run_id": str(run_id),
                "skill_name": skill.name,
                "exception_type": type(exc).__name__,
                "runtime_s": runtime_s,
            },
        )
        # Synchronous, no DB read — the loop is collapsing, so don't await anything here;
        # `emitted_count` is left unknown rather than risk a query during cancellation.
        _capture_run_finished(
            team=team,
            config=config,
            skill=skill,
            run_id=run_id,
            task_run_id=None,
            status=TaskRun.Status.CANCELLED.value,
            runtime_s=runtime_s,
            emitted_count=None,
        )
        raise


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
        # `signals_scout` is the harness's own scope posture: project reads +
        # INTERNAL_SCOPES + the scout's `signal_scout_internal:write`, plus a narrow
        # allowlist of user-facing writes (`SCOUT_USER_WRITE_SCOPES`, e.g.
        # `notebook:write`) so a finding can produce a durable artifact. It reports
        # `has_write_scopes=True` so the MCP server doesn't enable read-only-mode tool
        # filtering. Without that opt-out, the MCP layer would categorically strip every
        # tool annotated `readOnlyHint: false` — including the agent's own `remember`,
        # `forget`, and `emit_finding` tools — even though the OAuth token does carry the
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
        # Keep the per-turn poll budget at the run's runtime cap so the dropped-finalization
        # salvage fires before the activity's `start_to_close_timeout` (DEFAULT_MAX_RUNTIME_S +
        # ACTIVITY_SLACK_S) cancels the activity. Default budget (MAX_POLL_SECONDS) exceeds the
        # ceiling and would let the activity die before salvage could return the written summary.
        max_poll_seconds=DEFAULT_MAX_RUNTIME_S,
        # The close-out is free-text markdown — if the agent ends with prose or malformed JSON
        # instead of a SignalScoutRunSummary object, keep the raw text as the summary rather than
        # failing the whole run. A failed run never finalizes, so its scan-position close-out is
        # lost and the next run inherits a doubled scan delta.
        fallback_from_text=lambda text: SignalScoutRunSummary(summary=text),
    )
    try:
        # Persist the agent's end-of-turn close-out so non-emitting runs leave a
        # discoverable trace for future-run dedupe. Failure paths skip this on
        # purpose — the bridge row keeps its empty default and the linked TaskRun
        # carries the error context.
        await database_sync_to_async(_finalize_run_summary, thread_sensitive=False)(
            run_id=run_id,
            team_id=team.parent_team_id or team.id,
            summary=result.summary,
        )
        return result.summary, str(session.task_run.id)
    finally:
        await session.end()


def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _resolve_config(team: Team, skill_name: str) -> SignalScoutConfig:
    """Get-or-create the (team, skill) config row, keyed on the canonical (parent) team.

    `get_or_create`'s lookup half isn't canonicalized by the TeamScopedRootMixin `save()`,
    so resolve to the parent id ourselves — else a child-team lookup misses the stored row
    and tries to create a duplicate, raising IntegrityError on the unique constraint.
    """
    config, _ = SignalScoutConfig.objects.unscoped().get_or_create(
        team_id=team.parent_team_id or team.id, skill_name=skill_name
    )
    return config


def _has_running_run(*, team_id: int, skill_name: str) -> bool:
    # Locked on (canonical team, skill_name) — different skills for the same team are
    # allowed to fan out (the coordinator can dispatch several due scouts per tick). Status flows
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


def _self_heal_stale_runs(team_id: int, skill_name: str) -> None:
    """No-op pending the task_run-based partial unique index follow-up.

    The original self-heal recovered RUNNING rows orphaned by a worker / sandbox
    crash, because a DB-level partial unique index on
    `(team_id, skill_name) WHERE status='running'` would otherwise block all
    future dispatches for the same (team, skill). That index was dropped during
    the 2026-05-21 restack — it referenced `SignalScoutRun.status`, which no
    longer exists on the slim bridge row (status lives on `task_run.status`).

    `_has_running_run` queries `task_run__status=IN_PROGRESS` so single-flighting
    still works at the app layer; stale bridge rows no longer block dispatch,
    they just take up space. The Tasks subsystem owns `task_run.status` and has
    its own timeout / cleanup path, so cross-product writes from here would be
    inappropriate. Restore real recovery logic once a `task_run.status`-based
    DB constraint lands as a follow-up.
    """
    _ = team_id, skill_name
    return


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


def _run_row_exists(run_id: Any, team_id: int) -> bool:
    return SignalScoutRun.objects.unscoped().filter(team_id=team_id, id=run_id).exists()


def _read_run_metrics(run_id: Any, team_id: int) -> tuple[int, str | None]:
    # The bridge row carries the authoritative emit tally (the emit tool bumps it in-run)
    # and the FK to the linked TaskRun — the join key into LLM analytics, where the
    # richer per-run metrics (tool calls, generations, tokens, cost) already live. Reading
    # both here keeps that linkage on failed runs too, not just clean completions. Returns
    # (0, None) when the row never persisted (failure before the first turn).
    row = (
        SignalScoutRun.objects.unscoped()
        .filter(team_id=team_id, id=run_id)
        .values_list("emitted_count", "task_run_id")
        .first()
    )
    if row is None:
        return 0, None
    emitted_count, task_run_id = row
    return emitted_count or 0, str(task_run_id) if task_run_id else None


def _capture_run_finished(
    *,
    team: Team,
    config: SignalScoutConfig,
    skill: LoadedSkill,
    run_id: Any,
    task_run_id: str | None,
    status: str,
    runtime_s: float,
    emitted_count: int | None,
) -> None:
    """Emit the scout-owned per-run analytics event.

    Complements the generic `task_run_completed` / `task_run_failed` events (which only
    differentiate scout runs by `origin_product="signals_scout"`) with the dimensions a
    scout experiment segments on: skill identity, body version, outcome, duration, and
    emit volume — keyed on the team so it joins both to the emit-side `signal_emitted`
    events and to the team-level experiment exposure. Best-effort: a capture failure must
    never fail or mask the run outcome.
    """
    try:
        posthoganalytics.capture(
            event="signals_scout_run_finished",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": skill.name,
                "skill_version": skill.version,
                "scout_config_id": str(config.id),
                "run_id": str(run_id),
                "task_run_id": task_run_id,
                "status": status,
                "runtime_seconds": round(runtime_s, 1),
                "emitted_count": emitted_count,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture run-finished analytics event",
            extra={"team_id": team.id, "run_id": str(run_id), "skill_name": skill.name},
        )


def _finalize_run_summary(*, run_id: Any, team_id: int, summary: str) -> None:
    # Targeted UPDATE rather than `.save()` — the row's other fields are untouched
    # by the agent's close-out, and `update()` skips the full model refresh.
    SignalScoutRun.objects.unscoped().filter(team_id=team_id, id=run_id).update(summary=summary)


def _step_name(skill: LoadedSkill) -> str:
    # Surfaces in the Task title and S3 log prefix. Keep terse — the sandbox truncates.
    safe = skill.name.replace(" ", "_")[:40]
    return f"signals_scout:{safe}"
