"""Temporal producer for pre-computed scout suggestions.

Mirrors the scout coordinator pair (`scout_coordinator.py` / `scout_scheduler.py`): a
schedule-driven coordinator plans the most-overdue eligible projects, fans out one fire-and-forget
child per project with deterministic ids, and stamps `last_requested_at` only for the children it
actually dispatched; each child runs one headless suggestion scan for one team. The planning,
gating, and persistence logic lives in `scout_harness/suggestions.py` (temporalio-free); this
module is the wiring.
"""

from __future__ import annotations

import json
import asyncio
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings as django_settings
from django.db import InterfaceError, OperationalError

import structlog
from asgiref.sync import async_to_sync
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.scout_harness.suggestions import (
    SUGGESTIONS_ACTIVITY_SLACK_S,
    SuggestionSettings,
    mark_generation_failed,
    parse_suggestion_settings,
    plan_suggestion_runs,
    read_suggestion_settings,
    stamp_requested,
)

logger = structlog.get_logger(__name__)

# Same grid as the scout coordinator so the two tick together and the per-tick cap is the only
# spend knob; the suggestion schedule is registered separately so it can be paused on its own.
SUGGESTIONS_COORDINATOR_INTERVAL_MINUTES = 30
# How long a per-team scan may sit unclaimed on the task queue before the run is given up.
SUGGESTIONS_ACTIVITY_QUEUE_WAIT = timedelta(minutes=SUGGESTIONS_COORDINATOR_INTERVAL_MINUTES)
SUGGESTIONS_COORDINATOR_WORKFLOW_NAME = "run-signals-scout-suggestions-coordinator"
SUGGESTIONS_COORDINATOR_SCHEDULE_ID = "signals-scout-suggestions-coordinator-schedule"


@dataclass(frozen=True)
class PlannedSuggestion:
    team_id: int
    tier: int


@dataclass(frozen=True)
class PlanSuggestionsInput:
    pass


@dataclass(frozen=True)
class PlanSuggestionsOutput:
    planned: list[PlannedSuggestion]
    # The settings snapshot the plan was made under, passed to every child so one tick uses one
    # max-runtime / model posture even if the flag changes mid-fan-out.
    settings_json: str


@dataclass(frozen=True)
class StampRequestedInput:
    team_ids: list[int]


@dataclass(frozen=True)
class SuggestionsCoordinatorInput:
    pass


@dataclass(frozen=True)
class SuggestionsCoordinatorOutput:
    planned_count: int
    started_count: int
    skipped_count: int


@dataclass(frozen=True)
class RunScoutSuggestionsInput:
    team_id: int
    tier: int | None = None
    settings_json: str | None = None
    # "schedule" (coordinator) or "manual" (management command / internal endpoint).
    triggered_by: str = "schedule"
    # The authenticated user behind a manual refresh. The scan acts as this user so an
    # RBAC-restricted caller cannot pull a batch minted under a more privileged member;
    # None (scheduled and command runs) falls back to the team's resolved acting user.
    acting_user_id: int | None = None


@dataclass(frozen=True)
class RunScoutSuggestionsOutput:
    team_id: int
    status: str
    task_run_id: str | None
    suggestion_count: int
    runtime_s: float
    skip_reason: str | None = None


def _settings_to_json(settings: SuggestionSettings) -> str:
    data = asdict(settings)
    data["team_allowlist"] = sorted(settings.team_allowlist)
    data["team_blocklist"] = sorted(settings.team_blocklist)
    return json.dumps(data)


def _settings_from_json(raw: str | None) -> SuggestionSettings:
    if not raw:
        return SuggestionSettings()
    return parse_suggestion_settings(json.loads(raw))


@activity.defn
async def plan_scout_suggestion_runs_activity(_input: PlanSuggestionsInput) -> PlanSuggestionsOutput:
    """Select the teams to refresh this tick, best first, capped by the flag payload."""
    async with Heartbeater():
        # Flag read off the DB thread pool, like the scout coordinator: the SDK call can block on
        # a cold cache and the DB pool is sized for DB-bound work.
        settings = await asyncio.to_thread(read_suggestion_settings)
        planned = await database_sync_to_async(plan_suggestion_runs, thread_sensitive=False)(settings)
    logger.info("scout_suggestions coordinator: planned", count=len(planned), enabled=settings.enabled)
    return PlanSuggestionsOutput(
        planned=[PlannedSuggestion(team_id=run.team_id, tier=run.tier) for run in planned],
        settings_json=_settings_to_json(settings),
    )


@activity.defn
async def stamp_requested_scout_suggestions_activity(stamp_input: StampRequestedInput) -> None:
    """Advance `last_requested_at` for the dispatched teams, so a fan-out failure re-plans them
    next tick rather than silently skipping a refresh window."""
    async with Heartbeater():
        await database_sync_to_async(stamp_requested, thread_sensitive=False)(stamp_input.team_ids)


@activity.defn
@close_db_connections
async def run_scout_suggestions_activity(input: RunScoutSuggestionsInput) -> RunScoutSuggestionsOutput:
    """One headless suggestion scan for one team. Never raises for a failed generation; the row
    records the failure and the result carries `status='failed'`."""
    # Deferred like the scout scheduler's runner import: the runner reaches back into this
    # package for the sandbox helpers, and `temporal/__init__.py` imports this module.
    from products.signals.backend.scout_harness.suggestions_runner import arun_scout_suggestions  # noqa: PLC0415

    settings = _settings_from_json(input.settings_json)
    try:
        async with Heartbeater():
            result = await arun_scout_suggestions(
                input.team_id,
                settings=settings,
                tier=input.tier,
                triggered_by=input.triggered_by,
                acting_user_id=input.acting_user_id,
            )
    except (OperationalError, InterfaceError):
        # Transient pooled-connection drop (pgbouncer recycle / failover / deploy). The coordinator
        # has already stamped `last_requested_at`, so this has to be recorded as a failure or the
        # team is simply suppressed until its next refresh with nothing to show for the attempt.
        logger.warning("scout_suggestions activity: transient DB failure", team_id=input.team_id, exc_info=True)
        try:
            await database_sync_to_async(mark_generation_failed, thread_sensitive=False)(
                input.team_id, task_run_id=None
            )
        except Exception:
            # The connection may still be down, in which case the breaker misses this attempt.
            logger.warning(
                "scout_suggestions activity: could not record transient DB failure",
                team_id=input.team_id,
                exc_info=True,
            )
        return RunScoutSuggestionsOutput(
            team_id=input.team_id, status="failed", task_run_id=None, suggestion_count=0, runtime_s=0.0
        )
    logger.info(
        "scout_suggestions activity finished",
        team_id=input.team_id,
        status=result.status,
        suggestion_count=result.suggestion_count,
        runtime_s=result.runtime_s,
        skip_reason=result.skip_reason,
    )
    return RunScoutSuggestionsOutput(
        team_id=result.team_id,
        status=result.status,
        task_run_id=result.task_run_id,
        suggestion_count=result.suggestion_count,
        runtime_s=result.runtime_s,
        skip_reason=result.skip_reason,
    )


@workflow.defn(name="run-scout-suggestions")
class RunScoutSuggestionsWorkflow:
    """One team's suggestion scan. The activity owns the row lifecycle; the workflow only sets the
    timeout and retry posture."""

    @workflow.run
    async def run(self, input: RunScoutSuggestionsInput) -> RunScoutSuggestionsOutput:
        settings = _settings_from_json(input.settings_json)
        run_budget = timedelta(seconds=settings.max_runtime_s + SUGGESTIONS_ACTIVITY_SLACK_S)
        return await workflow.execute_activity(
            run_scout_suggestions_activity,
            input,
            start_to_close_timeout=run_budget,
            # Bounds the queue wait too: `start_to_close` only starts once a worker picks the
            # activity up, so without this a run-now's stable id would answer 409 for as long as
            # no compatible worker exists, and scheduled runs would stack under fresh tick ids.
            schedule_to_close_timeout=run_budget + SUGGESTIONS_ACTIVITY_QUEUE_WAIT,
            heartbeat_timeout=timedelta(minutes=2),
            # No retries: a failed generation is recorded on the row and re-planned by the
            # coordinator after the breaker cooldown; a retry loop here would spend blindly.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn(name=SUGGESTIONS_COORDINATOR_WORKFLOW_NAME)
class ScoutSuggestionsCoordinatorWorkflow:
    """Plan the overdue eligible teams, fan out one abandoned child per team, stamp after dispatch.

    Child ids are deterministic per `(team, tick, idx)` with `REJECT_DUPLICATE`, so a coordinator
    retry within a tick skips instead of double-launching. `ParentClosePolicy.ABANDON` keeps the
    coordinator's lifetime to seconds regardless of fan-out size.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SuggestionsCoordinatorInput:
        return SuggestionsCoordinatorInput()

    @workflow.run
    async def run(self, _input: SuggestionsCoordinatorInput) -> SuggestionsCoordinatorOutput:
        plan = await workflow.execute_activity(
            plan_scout_suggestion_runs_activity,
            PlanSuggestionsInput(),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not plan.planned:
            return SuggestionsCoordinatorOutput(0, 0, 0)

        # `workflow_id` is per tick (the schedule appends the scheduled time) and stable across a
        # retry of the same tick, which is what makes the child ids below dedupe correctly.
        tick_id = workflow.info().workflow_id
        started = 0
        skipped = 0
        dispatched: list[int] = []
        for idx, planned in enumerate(plan.planned):
            child_id = f"scout-suggestions-run-{planned.team_id}-{tick_id}-{idx}"
            try:
                await workflow.start_child_workflow(
                    RunScoutSuggestionsWorkflow.run,
                    RunScoutSuggestionsInput(
                        team_id=planned.team_id, tier=planned.tier, settings_json=plan.settings_json
                    ),
                    id=child_id,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                skipped += 1
            dispatched.append(planned.team_id)

        await workflow.execute_activity(
            stamp_requested_scout_suggestions_activity,
            StampRequestedInput(team_ids=dispatched),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        return SuggestionsCoordinatorOutput(
            planned_count=len(plan.planned), started_count=started, skipped_count=skipped
        )


def manual_suggestions_workflow_id(team_id: int) -> str:
    """Stable per-team id for a run-now, so a second trigger while one is in flight is rejected."""
    return f"scout-suggestions-manual-run-{team_id}"


@async_to_sync
async def start_manual_scout_suggestions_run(client: Client, *, team_id: int, acting_user_id: int | None = None) -> str:
    """Dispatch one on-demand suggestion scan for a team, bypassing the planner and its cap.

    Single-flight at the Temporal server: `ALLOW_DUPLICATE` lets the stable id be reused once the
    prior run closed, `FAIL` rejects a second trigger while one is still running (raises
    `WorkflowAlreadyStartedError` for the caller to map to a 409). A started run also stamps the
    planner state, so the coordinator treats it as this window's refresh instead of dispatching a
    second scan for the same team on its next tick.
    """
    workflow_id = manual_suggestions_workflow_id(team_id)
    settings = read_suggestion_settings()
    await client.start_workflow(
        RunScoutSuggestionsWorkflow.run,
        RunScoutSuggestionsInput(
            team_id=team_id,
            settings_json=_settings_to_json(settings),
            triggered_by="manual",
            acting_user_id=acting_user_id,
        ),
        id=workflow_id,
        task_queue=django_settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
    )
    try:
        await database_sync_to_async(stamp_requested, thread_sensitive=False)([team_id])
    except Exception:
        # The scan is already running; a lost stamp costs at worst one extra scheduled scan,
        # which is cheaper than reporting a dispatched run as a failure.
        logger.warning("scout_suggestions: manual dispatch stamp failed", team_id=team_id, exc_info=True)
    return workflow_id


__all__ = [
    "SUGGESTIONS_COORDINATOR_INTERVAL_MINUTES",
    "SUGGESTIONS_COORDINATOR_SCHEDULE_ID",
    "SUGGESTIONS_COORDINATOR_WORKFLOW_NAME",
    "RunScoutSuggestionsInput",
    "RunScoutSuggestionsOutput",
    "RunScoutSuggestionsWorkflow",
    "ScoutSuggestionsCoordinatorWorkflow",
    "SuggestionsCoordinatorInput",
    "plan_scout_suggestion_runs_activity",
    "run_scout_suggestions_activity",
    "stamp_requested_scout_suggestions_activity",
    "start_manual_scout_suggestions_run",
]
