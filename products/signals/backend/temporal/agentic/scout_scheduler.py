from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import InterfaceError, OperationalError

import structlog
import temporalio
from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.daily_limit import capture_signal_report_daily_limit_paused, daily_report_limit_gate
from products.signals.backend.quota import is_team_signals_quota_limited
from products.signals.backend.scout_harness.limits import (
    TRIGGERED_BY_MANUAL,
    TRIGGERED_BY_SCHEDULE,
    TRIGGERED_BY_WORKFLOW,
    WORKFLOW_HARD_CEILING_S,
)
from products.signals.backend.temporal import metrics

if TYPE_CHECKING:
    # Type-only: importing the harness runner at module load would close the cycle
    # runner -> temporal.agentic -> scout_coordinator -> scout_scheduler -> runner.
    from products.signals.backend.scout_harness.runner import RunResult

logger = structlog.get_logger(__name__)


@dataclass
class RunSignalsScoutInput:
    team_id: int
    skill_name: str
    skill_version: int | None = None
    repository: str | None = None
    # "schedule" (coordinator dispatch, including breaker probes), "manual" (the `run` endpoint)
    # or "workflow" (a workflow step that runs a scout). Only scheduled failures feed the
    # failure-streak breaker; the default keeps in-flight workflow histories decoding to today's
    # behavior. See `scout_harness/limits.py` for the vocabulary.
    triggered_by: str = TRIGGERED_BY_SCHEDULE


@dataclass
class RunSignalsScoutOutput:
    run_id: str | None
    task_run_id: str | None
    status: str | None
    runtime_s: float
    skill_name: str
    skill_version: int
    skip_reason: str | None = None


def _to_output(result: RunResult) -> RunSignalsScoutOutput:
    return RunSignalsScoutOutput(
        run_id=result.run_id,
        task_run_id=result.task_run_id,
        status=result.status,
        runtime_s=result.runtime_s,
        skill_name=result.skill_name,
        skill_version=result.skill_version,
        skip_reason=result.skip_reason,
    )


@temporalio.activity.defn
@close_db_connections
async def run_signals_scout_activity(input: RunSignalsScoutInput) -> RunSignalsScoutOutput:
    """One scheduled scout run for a (team, skill) pair.

    The activity itself never raises — failures are persisted on the run row and the
    workflow sees a `status='failed'` outcome. This matches the spec's "fail safe and
    silent" rule: a bad run does not retry blindly.

    The long-lived worker pools its DB connections through pgbouncer, so a pool recycle,
    failover, or deploy can leave a stale pooled connection that raises `OperationalError`
    the next time it's used. `@close_db_connections` evicts stale connections around the
    activity, and the `(OperationalError, InterfaceError)` guard below catches a blip that
    lands mid-run — including the runner's early guards and its own except-handler reads,
    which run outside the run-row try/except — so a transient drop is reported as a failed
    run rather than escaping the activity and breaching the "never raises" contract.
    """
    # Skip the run when the team is over its Signals credits quota or its daily report limit,
    # before any LLM work: a scout run exists to feed signals into the pipeline, and ingestion
    # drops them while either limit binds.
    team = await Team.objects.select_related("organization").aget(pk=input.team_id)
    quota_limited = await database_sync_to_async(is_team_signals_quota_limited, thread_sensitive=False)(team.api_token)
    daily_gate = await database_sync_to_async(daily_report_limit_gate, thread_sensitive=False)(team)
    # Captured whenever the daily gate binds — even when the quota skip below wins the
    # single-status run counter — so the daily-limit event stream stays complete on co-bound days.
    if daily_gate.limited:
        capture_signal_report_daily_limit_paused(team, report_id=None, stage="scout_run", gate=daily_gate)
    if quota_limited:
        logger.info(
            "signals_scout: skipping run, team over signals_credits quota",
            team_id=input.team_id,
            skill_name=input.skill_name,
        )
        metrics.increment_scout_run("quota_limited")
        return RunSignalsScoutOutput(
            run_id=None,
            task_run_id=None,
            status=None,
            runtime_s=0.0,
            skill_name=input.skill_name,
            skill_version=input.skill_version or 0,
            skip_reason="quota_limited",
        )
    if daily_gate.limited:
        logger.info(
            "signals_scout: skipping run, team over daily report limit",
            team_id=input.team_id,
            skill_name=input.skill_name,
        )
        metrics.increment_scout_run("daily_report_limit")
        return RunSignalsScoutOutput(
            run_id=None,
            task_run_id=None,
            status=None,
            runtime_s=0.0,
            skill_name=input.skill_name,
            skill_version=input.skill_version or 0,
            skip_reason="daily_report_limit",
        )

    # Deferred to break the runner <-> temporal import cycle (see the TYPE_CHECKING note
    # above): importing the runner at module load leaves RunResult undefined when runner
    # is the import entry point. Imported here at call time, after both modules are loaded.
    from products.signals.backend.scout_harness.runner import arun_signals_scout  # noqa: PLC0415

    try:
        async with Heartbeater():
            result = await arun_signals_scout(
                team_id=input.team_id,
                skill_name=input.skill_name,
                skill_version=input.skill_version,
                repository=input.repository,
                triggered_by=input.triggered_by,
            )
    except (OperationalError, InterfaceError):
        # Transient DB connection drop (pgbouncer pool recycle / failover / deploy). Stay
        # fail-safe and silent: report a failed run for this tick rather than raising. The
        # decorator already evicted the dead connection; the next scheduled tick retries on
        # a fresh one. `"failed"` mirrors `TaskRun.Status.FAILED.value`.
        metrics.increment_scout_run("failed")
        logger.warning(
            "signals_scout activity: transient DB connection failure, reporting failed run",
            team_id=input.team_id,
            skill_name=input.skill_name,
            exc_info=True,
        )
        return RunSignalsScoutOutput(
            run_id=None,
            task_run_id=None,
            status="failed",
            runtime_s=0.0,
            skill_name=input.skill_name,
            skill_version=input.skill_version or 0,
        )
    metrics.increment_scout_run(result.status or "unknown")
    logger.info(
        "signals_scout activity finished",
        team_id=input.team_id,
        skill_name=input.skill_name,
        run_id=result.run_id,
        status=result.status,
        runtime_s=result.runtime_s,
        skip_reason=result.skip_reason,
    )
    return _to_output(result)


@temporalio.workflow.defn
class RunSignalsScoutWorkflow:
    """Drives one scheduled scout run.

    The activity owns the run-row lifecycle (insert/update). The workflow's job is just
    to spawn the activity with the right timeout and retry posture, and surface the
    outcome to the scheduler.
    """

    @temporalio.workflow.run
    async def run(self, input: RunSignalsScoutInput) -> RunSignalsScoutOutput:
        return await temporalio.workflow.execute_activity(
            run_signals_scout_activity,
            input,
            start_to_close_timeout=timedelta(seconds=WORKFLOW_HARD_CEILING_S),
            heartbeat_timeout=timedelta(minutes=2),
            # No retries: failures are persisted as `status='failed'` on the run row and
            # we don't want a bad skill / prompt to spin retry loops. The next scheduled
            # tick will try again.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


def _off_schedule_run_workflow_id(namespace: str, team_id: int, skill_name: str) -> str:
    """Deterministic workflow id for an off-schedule scout run.

    Distinct namespace from the coordinator's per-tick child ids (`signals-scout-run-…`) so an
    off-schedule run can't collide with a scheduled one, and one namespace per trigger source so
    the two off-schedule paths single-flight independently at the Temporal server. Stable per
    `(team, skill)` so the id-conflict policy in the start helpers can single-flight against it.

    The readable skill fragment is truncated for legibility, but a digest of the *full*
    skill name is appended so two custom scouts sharing the first 60 chars still map to
    distinct ids — otherwise `WorkflowIDConflictPolicy.FAIL` would 409 one scout while the
    other (truncation-twin) is running, even though it has no in-flight run of its own.
    """
    safe_skill = skill_name.replace(" ", "_")[:60]
    digest = hashlib.sha256(skill_name.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"{namespace}-{team_id}-{safe_skill}-{digest}"


def manual_run_workflow_id(team_id: int, skill_name: str) -> str:
    """Deterministic workflow id for an on-demand (`run now`) scout run."""
    return _off_schedule_run_workflow_id("signals-scout-manual-run", team_id, skill_name)


def workflow_triggered_run_workflow_id(team_id: int, skill_name: str) -> str:
    """Deterministic workflow id for a run fired by a workflow step that runs a scout."""
    return _off_schedule_run_workflow_id("signals-scout-workflow-run", team_id, skill_name)


@async_to_sync
async def _start_off_schedule_run(
    client: Client, *, workflow_id: str, team_id: int, skill_name: str, source: str
) -> str:
    """Start one `RunSignalsScoutWorkflow` off-schedule under `workflow_id`; return the id.

    Reuses `RunSignalsScoutWorkflow`, so an off-schedule run inherits every guard the scheduled
    path has — the activity's Signals-credits quota check, and the runner's withheld-skill
    denylist, stale-run self-heal, and single-flight. It does NOT honor the per-scout schedule or
    `last_run_at`: an off-schedule run deliberately leaves the cadence untouched — which is also
    why its failures don't feed the failure-streak breaker (the threshold is sized on the
    schedule), while an off-schedule success still clears the streak and can resume a
    breaker-paused lane.

    Single-flight is enforced at the Temporal server, so a trigger can't be gamed into stacking
    concurrent runs of the same scout: `ALLOW_DUPLICATE` lets the stable id be reused once the
    prior run under it has closed, while `FAIL` rejects a second trigger while one is still
    running — raising `WorkflowAlreadyStartedError` for the caller to map to a 409.
    """
    await client.start_workflow(
        RunSignalsScoutWorkflow.run,
        RunSignalsScoutInput(team_id=team_id, skill_name=skill_name, triggered_by=source),
        id=workflow_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
    )
    return workflow_id


def start_manual_signals_scout_run(client: Client, *, team_id: int, skill_name: str) -> str:
    """Dispatch one on-demand scout run on the signals task queue; return its workflow id."""
    return _start_off_schedule_run(
        client,
        workflow_id=manual_run_workflow_id(team_id, skill_name),
        team_id=team_id,
        skill_name=skill_name,
        source=TRIGGERED_BY_MANUAL,
    )


def start_workflow_signals_scout_run(client: Client, *, team_id: int, skill_name: str) -> str:
    """Dispatch one workflow-triggered scout run on the signals task queue; return its workflow id.

    Its own id namespace, so a workflow fire and a human's "Run now" single-flight separately at
    the Temporal server — a human testing a scout shouldn't 409 the automation, or vice versa. The
    overlap that actually matters (one live run per `(team, skill)`) is still caught by the
    runner's own single-flight and the callers' in-flight pre-check, both of which are
    source-agnostic.
    """
    return _start_off_schedule_run(
        client,
        workflow_id=workflow_triggered_run_workflow_id(team_id, skill_name),
        team_id=team_id,
        skill_name=skill_name,
        source=TRIGGERED_BY_WORKFLOW,
    )
