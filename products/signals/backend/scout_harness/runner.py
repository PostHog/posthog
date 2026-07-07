from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.utils import timezone

import posthoganalytics

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import STEP_SCOUT, resolve_agent_runtime
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills
from products.signals.backend.scout_harness.limits import DEFAULT_MAX_RUNTIME_S, STALE_RUN_CUTOFF_S
from products.signals.backend.scout_harness.model_selection import resolve_scout_model
from products.signals.backend.scout_harness.prompt import SignalScoutRunSummary, build_run_prompt
from products.signals.backend.scout_harness.skill_loader import (
    LoadedSkill,
    load_skill_for_run,
    skill_uses_report_channel,
)
from products.signals.backend.scout_harness.team_limits import withheld_skills_for_team
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_acting_user_id_for_team,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = logging.getLogger(__name__)

# Reuse the report-research sandbox env. Same posture: full repo on disk, restricted
# network, MCP read scopes injected. Split out later if the agent needs different policy.
SIGNALS_SCOUT_SANDBOX_ENV_NAME = SIGNALS_REPORT_RESEARCH_ENV_NAME

# The report channel (emit_report/edit_report) is opt-in per skill. A scout's sandbox token
# carries the report-write scope ONLY when its skill listed one of these in `allowed_tools` (see
# the posture selection where the sandbox context is built). A baseline scout never carries that
# scope, so the MCP server strips the report tools from its toolset — they can't bleed into a run
# that didn't opt in. `views._assert_report_tool_opted_in` is the matching fail-closed gate on the
# write itself. `REPORT_CHANNEL_TOOLS` / `skill_uses_report_channel` live in `skill_loader` so the
# runner, prompt builder, and viewset all resolve the same opt-in set.


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

    # Honor the per-scout holdback denylist, resolved against the canonical project. Two effects:
    # (1) a direct run of a held-back scout is refused up front (so this manual path can't seed or
    # run a scout the flag withholds), and (2) the canonical sync below is passed the denylist so
    # running *any* scout on a held-back team can't seed the other withheld scouts' rows as a side
    # effect. In local dev there's no flag payload, so this resolves empty and nothing is blocked.
    withheld = await database_sync_to_async(withheld_skills_for_team, thread_sensitive=False)(
        team.parent_team_id or team.id
    )
    if skill_name in withheld:
        logger.info(
            "signals_scout: skipping run, scout is withheld from this team",
            extra={"team_id": team_id, "skill_name": skill_name},
        )
        return RunResult(
            run_id=None,
            task_run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name=skill_name,
            skill_version=skill_version or 0,
            skip_reason="scout is withheld from this team",
        )

    # Sync canonical signals-scout-* skills before we resolve the skill the run asked for.
    # Creates rows for newly-shipped specialists, updates harness-seeded rows the team
    # hasn't edited, and leaves forked / tombstoned rows alone. Failures here should not
    # crash the run — we log and continue with whatever skills the team already has.
    try:
        await database_sync_to_async(sync_canonical_skills, thread_sensitive=False)(team, withheld_skill_names=withheld)
    except Exception:
        logger.exception(
            "signals_scout: canonical skill sync failed; continuing with existing team skills",
            extra={"team_id": team_id},
        )
    skill = await database_sync_to_async(load_skill_for_run, thread_sensitive=False)(
        team, skill_name, version=skill_version
    )
    config = await database_sync_to_async(_resolve_config, thread_sensitive=False)(team, skill.name)

    # Stale-run recovery, before the skip-if-running guard below. A scout run writes its own
    # terminal `task_run.status` from inside the activity; if the worker/sandbox dies hard
    # mid-run that write never lands, leaving the TaskRun stuck `IN_PROGRESS` — which would
    # otherwise block every future dispatch for this `(team, skill)` forever via
    # `_has_running_run`. Reap such orphans here so the lane self-heals. Keyed on the same
    # canonical `(team, skill_name)` the guard uses so it reaps exactly the rows the guard sees.
    await database_sync_to_async(_self_heal_stale_runs, thread_sensitive=False)(
        team.parent_team_id or team.id, skill.name
    )

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

    # Resolve the acting user up front. Scouts don't clone a repo on the cadence path, so they
    # don't need a GitHub integration — `resolve_acting_user_id_for_team` prefers the GitHub
    # creator when present but falls back to any active org member, so a team that never connected
    # GitHub still runs (these dominated the fleet failure rate when the run instead crashed ~5s
    # into `_spawn_and_run` and booked a bogus `failed`). The only remaining short-circuit is the
    # genuine "no active user to act as" case; like the withheld / in-flight skips it leaves no
    # row, no lifecycle event, and a `skip_reason` the coordinator can surface — not a failure.
    user_id = await database_sync_to_async(resolve_acting_user_id_for_team, thread_sensitive=False)(team.id)
    if user_id is None:
        logger.info(
            "signals_scout: skipping run, no active user to act as for team",
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
            skip_reason="no active user to act as for team",
        )

    started = time.monotonic()
    # Pre-mint the bridge row's UUID so the prompt can reference it before the row
    # exists. The TaskRun is created inside `MultiTurnSession.start`; the bridge row is
    # inserted via its `on_task_run_created` hook — after the TaskRun exists but before
    # the agent's first turn — so first-turn finding emits can resolve the run by id.
    run_id = uuid7()
    started_at = timezone.now()

    # Resolve the scout's agent model from the `scouts-model-selection` gate. A `None` model keeps the
    # agent-server default; an override routes this run on that model, paired with the runtime adapter
    # that can serve it (the agent server can't route a model without one). The flag payload is a
    # per-team, per-scout model distribution, bucketed per run on `run_id` — so a scout can A/B/n
    # across models against itself across runs. Resolved once here so the whole run is consistent.
    # Off the event loop — the flag read does blocking network I/O.
    scout_model = await database_sync_to_async(resolve_scout_model, thread_sensitive=False)(
        team, skill.name, str(run_id)
    )

    # A runtime pin takes precedence over the scout-model gate and replaces it wholesale —
    # runtime/model/effort move as a set so a Codex runtime never pairs with a glm model.
    # Model-only payload entries are deliberately ignored for scout: the gate supplies
    # model+runtime as a pair, and overriding one without the other would mis-route.
    agent_runtime = await database_sync_to_async(resolve_agent_runtime, thread_sensitive=False)(team_id, STEP_SCOUT)
    if agent_runtime.runtime_adapter:
        runtime_adapter: str | None = agent_runtime.runtime_adapter
        model = agent_runtime.model
        reasoning_effort: str | None = agent_runtime.reasoning_effort
    else:
        runtime_adapter = scout_model.runtime_adapter
        model = scout_model.model
        reasoning_effort = None
    try:
        last_message, task_run_id = await _spawn_and_run(
            team=team,
            config=config,
            run_id=run_id,
            started_at=started_at,
            skill=skill,
            repository=repository,
            verbose=verbose,
            user_id=user_id,
            model=model,
            runtime_adapter=runtime_adapter,
            reasoning_effort=reasoning_effort,
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
            status=tasks_facade.TaskRunStatus.COMPLETED.value,
            runtime_s=runtime_s,
            emitted_count=emitted_count,
        )
        return RunResult(
            run_id=str(run_id),
            task_run_id=task_run_id,
            status=tasks_facade.TaskRunStatus.COMPLETED.value,
            last_message=last_message,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )
    except Exception as exc:
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
            status=tasks_facade.TaskRunStatus.FAILED.value,
            runtime_s=runtime_s,
            emitted_count=emitted_count,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        return RunResult(
            run_id=str(run_id) if row_persisted else None,
            task_run_id=None,
            status=tasks_facade.TaskRunStatus.FAILED.value,
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
            status=tasks_facade.TaskRunStatus.CANCELLED.value,
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
    user_id: int,
    model: str | None,
    runtime_adapter: str | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, str]:
    """Spawn the sandbox, create the bridge row before the first turn, run the agent.

    `user_id` is the acting user resolved (and validated non-None) by the caller. `model`,
    `runtime_adapter`, and `reasoning_effort` are the agent runtime overrides (`model` paired with the
    `runtime_adapter` that serves it — the agent server derives the provider from it; all `None` keeps
    the agent-server default Claude runtime). Returns `(last_message, task_run_id)`.
    """
    sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
        team.id,
        SIGNALS_SCOUT_SANDBOX_ENV_NAME,
        tasks_facade.SandboxNetworkAccessLevel.TRUSTED,
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
        #
        # A scout that opted into the report channel gets `signals_scout_reports` instead —
        # the same posture plus `signal_scout_report:write` — so the MCP server exposes the
        # emit_report/edit_report tools. Every other scout gets plain `signals_scout` and never
        # sees them.
        posthog_mcp_scopes=(
            "signals_scout_reports" if skill_uses_report_channel(skill.allowed_tools) else "signals_scout"
        ),
        # `None` keeps the agent-server default; an override pins the whole run on one model
        # (the `scouts-model-selection` gate routes it here). The model the gateway actually serves
        # is tagged on each $ai_generation, so per-run model is queryable in LLM analytics.
        model=model,
        # Paired with `model`: the agent server derives the LLM provider from the runtime.
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
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
        # Lifecycle start marker. The row + TaskRun now exist and the run has cleared the
        # reap + single-flight guards, so this counts exactly the runs that actually start —
        # a skipped dispatch emits nothing. Pairs with `signals_scout_run_finished` for
        # event-derived throughput and stall detection (started with no finished = a run
        # that died before finalize), with no warehouse-sync lag.
        _capture_run_started(
            team=team,
            config=config,
            skill=skill,
            run_id=run_id,
            task_run_id=str(task_run.id),
        )

    session, result = await MultiTurnSession.start(
        prompt=prompt,
        context=context,
        model=SignalScoutRunSummary,
        step_name=_step_name(skill),
        verbose=verbose,
        origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT,
        # Tag every scout $ai_generation with a coarse pipeline stage so scout spend is
        # splittable out of the ai_product='signals' bucket (scouts carry no signal_report_id).
        # Constant 'scout' keeps ai_stage a low-cardinality stage enum (peer of research /
        # repo_selection / implementation); per-scout granularity comes from scout_name (task_title).
        ai_stage="scout",
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
            task_run__status__in=(tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS),
        )
        .exists()
    )


def _self_heal_stale_runs(team_id: int, skill_name: str) -> None:
    """Reap orphaned in-flight runs so a dead run can't block the lane forever.

    A scout run writes its own terminal `task_run.status` from inside the activity. If the
    worker / sandbox dies hard mid-run (SIGKILL, pod eviction, sandbox loss), that write
    never lands and the TaskRun is frozen at `QUEUED`/`IN_PROGRESS`. `_has_running_run`
    then single-flights against that frozen row and skips every future dispatch for this
    `(team, skill)` indefinitely — there is no other release. Nothing else reconciles it:
    Temporal has already torn the workflow down (the activity is killed at
    `WORKFLOW_HARD_CEILING_S` with `maximum_attempts=1`), and the Tasks cleanup path does
    not cover a crashed worker.

    A run older than `STALE_RUN_CUTOFF_S` (a generous multiple of that ceiling) cannot
    still be legitimately executing, so it is an orphan and we mark it failed. The cutoff's
    slack means a run merely at the wall — about to fail or finish on its own — is never
    reaped out from under itself. Best-effort and silent: a failure to reap one row must
    never block the new run, so each is guarded independently.
    """
    cutoff = timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S)
    stale_runs = list(
        SignalScoutRun.objects.unscoped()
        .filter(
            team_id=team_id,
            skill_name=skill_name,
            task_run__status__in=(tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS),
            task_run__created_at__lt=cutoff,
        )
        .select_related("task_run")
    )
    if not stale_runs:
        return
    # Resolve the team once, only when there is actually something to reap, so the reaped
    # event carries the same team / groups shape as the other scout lifecycle events.
    team = _get_team(team_id)
    now = timezone.now()
    for run in stale_runs:
        try:
            task_run = run.task_run
            # Read the pre-reap status / age off the loaded bridge instance before the claim:
            # the conditional update below doesn't refresh it, so these stay the original values.
            status_before = task_run.status
            age_seconds = (now - task_run.created_at).total_seconds()
            # Compare-and-set claim on the status transition. Two triggers for the same
            # `(team, skill)` can reach this self-heal concurrently and load the same stale
            # row; the conditional UPDATE lets exactly one win — the other matches zero rows
            # once the first commits `FAILED`. Only the winner falls through to emit, so a
            # single stranded run can't double-count in the worker-death / mass-stall signal.
            claimed = tasks_facade.claim_and_fail_stale_run(
                task_run.id,
                "Scout run abandoned: no terminal status past the runtime ceiling "
                "(worker/sandbox lost before finalize).",
            )
            if not claimed:
                continue
            logger.warning(
                "signals_scout: reaped stale in-progress run before dispatch",
                extra={
                    "team_id": team_id,
                    "skill_name": skill_name,
                    "run_id": str(run.id),
                    "task_run_id": str(run.task_run_id),
                },
            )
            # A reaped run never reaches the finalize path, so it emits no
            # `signals_scout_run_finished`. This event makes the strand observable with no
            # warehouse lag — a spike is the worker-death / mass-stall shape, caught within a
            # tick of the cutoff rather than days late.
            _capture_run_reaped(
                team=team,
                skill_name=skill_name,
                run_id=run.id,
                task_run_id=str(run.task_run_id),
                status_before=status_before,
                age_seconds=age_seconds,
            )
        except Exception:
            logger.exception(
                "signals_scout: failed to reap stale in-progress run; continuing",
                extra={"team_id": team_id, "skill_name": skill_name, "run_id": str(run.id)},
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


def _capture_run_started(
    *,
    team: Team,
    config: SignalScoutConfig,
    skill: LoadedSkill,
    run_id: Any,
    task_run_id: str,
) -> None:
    """Emit the scout-owned run-started analytics event.

    The lifecycle counterpart to `signals_scout_run_finished`, fired once the TaskRun + bridge
    row exist and the run has cleared the reap + single-flight guards. Keyed on the team (same
    shape as the finished event) so the two join on `run_id`: `started` minus `finished` is the
    in-flight / stalled set, and a `started` with no `finished` is a run that died before
    finalize — an event-derived stall signal with no warehouse lag. Best-effort: a capture
    failure must never block the run.
    """
    try:
        posthoganalytics.capture(
            event="signals_scout_run_started",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": skill.name,
                "skill_version": skill.version,
                "scout_config_id": str(config.id),
                "run_id": str(run_id),
                "task_run_id": task_run_id,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture run-started analytics event",
            extra={"team_id": team.id, "run_id": str(run_id), "skill_name": skill.name},
        )


def _capture_run_reaped(
    *,
    team: Team,
    skill_name: str,
    run_id: Any,
    task_run_id: str,
    status_before: str,
    age_seconds: float,
) -> None:
    """Emit a scout-owned event when a stranded run is reaped (see `_self_heal_stale_runs`).

    A run orphaned by a hard worker death never reaches the finalize path, so it emits no
    `signals_scout_run_finished` — the reap is otherwise visible only in the logs. This event
    surfaces the strand directly: a rising count is the worker-death / mass-stall shape, and
    `status_before` + `age_seconds` distinguish a routine one-off from a fleet event. Keyed on
    the team to match the other scout lifecycle events. Best-effort: a capture failure must
    never block the reap or the new run.
    """
    try:
        posthoganalytics.capture(
            event="signals_scout_run_reaped",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": skill_name,
                "run_id": str(run_id),
                "task_run_id": task_run_id,
                "status_before": status_before,
                "age_seconds": round(age_seconds, 1),
                "stale_cutoff_seconds": STALE_RUN_CUTOFF_S,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture run-reaped analytics event",
            extra={"team_id": team.id, "run_id": str(run_id), "skill_name": skill_name},
        )


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
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Emit the scout-owned per-run analytics event.

    Complements the generic `task_run_completed` / `task_run_failed` events (which only
    differentiate scout runs by `origin_product="signals_scout"`) with the dimensions a
    scout experiment segments on: skill identity, body version, outcome, duration, and
    emit volume — keyed on the team so it joins both to the emit-side `signal_emitted`
    events and to the team-level experiment exposure. Best-effort: a capture failure must
    never fail or mask the run outcome.

    On `status='failed'`, `error_type` (the exception class) and a truncated `error_message`
    are attached so the failure rate is breakable down by cause without digging into worker
    logs — the bulk of scout failures fail in this layer before the `process-task` workflow's
    own `task_run_failed` event ever fires, so this is the only event that carries their reason.
    """
    properties: dict[str, Any] = {
        "skill_name": skill.name,
        "skill_version": skill.version,
        "scout_config_id": str(config.id),
        "run_id": str(run_id),
        "task_run_id": task_run_id,
        "status": status,
        "runtime_seconds": round(runtime_s, 1),
        "emitted_count": emitted_count,
    }
    # Only attach failure context on failed runs — keeps successful / cancelled events clean
    # rather than carrying explicit-null error fields on every event.
    if error_type is not None:
        properties["error_type"] = error_type
        properties["error_message"] = error_message
    try:
        posthoganalytics.capture(
            event="signals_scout_run_finished",
            distinct_id=str(team.uuid),
            properties=properties,
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
