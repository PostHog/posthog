"""The Dreaming Agent coordinator + per-team run workflow.

A nightly Temporal schedule fires the ``DreamingCoordinatorWorkflow``, which:

1. Enrolls every signals-enabled team (reusing the `signals-scout` flag payload allowlist —
   the same enrollment surface as the scout coordinator).
2. Force-enables the mandatory dreaming scout config for each enrolled team
   (``force_enable_dreaming``) so the dreaming run can never be turned opt-in.
3. Computes how overdue each team's dreaming run is and dispatches the most-overdue first,
   bounded per tick — exactly the scout coordinator's idiom.
4. Fans out a child ``RunDreamingWorkflow`` per team with ``ParentClosePolicy.ABANDON`` and
   deterministic per-tick workflow IDs, then stamps ``last_run_at`` only for teams it
   dispatched.

The child workflow runs the heavy per-team work in activities with bounded timeouts.
"""

from __future__ import annotations

import json
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.temporal.agentic.scout_coordinator import (
    _enrolled_team_ids,
    _participating_teams,
    _read_flag_payload,
)
from products.signals.backend.temporal.dreaming.enrollment import DREAMING_SKILL_NAME, force_enable_dreaming

logger = structlog.get_logger(__name__)
_py_logger = logging.getLogger(__name__)

# Bound dreaming dispatches per nightly tick. Nightly + one run per team means this is a high
# ceiling in practice; it's a safety bound against a misconfigured huge enrollment.
MAX_DREAMING_RUNS_PER_TICK = 500

# Grace on the due-check so a team a few seconds short of its interval still counts as due,
# mirroring the scout coordinator's stamp-jitter tolerance.
DUE_GRACE_SECONDS = 300


@dataclass
class DreamingTeamRun:
    """One unit of fan-out: a team whose nightly dreaming run is due."""

    team_id: int


@dataclass
class FetchDueDreamingRunsInput:
    pass


@dataclass
class FetchDueDreamingRunsOutput:
    due_runs: list[DreamingTeamRun]


@dataclass
class StampDreamingRunsInput:
    dispatched: list[DreamingTeamRun]


@dataclass
class DreamingCoordinatorInput:
    pass


@dataclass
class DreamingCoordinatorOutput:
    due_count: int
    started_count: int
    skipped_count: int


def _overdue_seconds(last_run_at: datetime | None, now: datetime, interval_minutes: int) -> float | None:
    """Seconds past due (down to ``-DUE_GRACE_SECONDS``), or None if not yet due."""
    if last_run_at is None:
        return float("inf")
    overdue = (now - last_run_at).total_seconds() - interval_minutes * 60
    return overdue if overdue >= -DUE_GRACE_SECONDS else None


def _collect_due_dreaming_runs(enrolled_team_ids: set[int]) -> list[DreamingTeamRun]:
    """Force-enable the dreaming config for each enrolled team and collect the due ones."""
    now = timezone.now()
    due: list[tuple[float, int]] = []
    for team in _participating_teams(enrolled_team_ids):
        try:
            config = force_enable_dreaming(team.id)
        except Exception:
            _py_logger.exception("dreaming coordinator: force-enable failed; skipping team", extra={"team_id": team.id})
            continue
        overdue = _overdue_seconds(config.last_run_at, now, config.run_interval_minutes)
        if overdue is None:
            continue
        due.append((overdue, team.id))

    due.sort(key=lambda item: (-item[0], item[1]))
    selected = due[:MAX_DREAMING_RUNS_PER_TICK]
    if len(due) > MAX_DREAMING_RUNS_PER_TICK:
        _py_logger.warning(
            "dreaming coordinator: more due than per-tick cap; deferring overflow",
            extra={"due": len(due), "cap": MAX_DREAMING_RUNS_PER_TICK},
        )
    # Stable order for deterministic child ids within the tick.
    runs = [DreamingTeamRun(team_id=team_id) for _, team_id in selected]
    runs.sort(key=lambda r: r.team_id)
    return runs


def _stamp_dispatched(dispatched: list[DreamingTeamRun]) -> None:
    if not dispatched:
        return
    team_ids = [run.team_id for run in dispatched]
    SignalScoutConfig.all_teams.filter(team_id__in=team_ids, skill_name=DREAMING_SKILL_NAME).update(
        last_run_at=timezone.now()
    )


@activity.defn
@scoped_temporal()
async def fetch_due_dreaming_runs_activity(_input: FetchDueDreamingRunsInput) -> FetchDueDreamingRunsOutput:
    async with Heartbeater():
        payload = await asyncio.to_thread(_read_flag_payload)
        enrolled = _enrolled_team_ids(payload)
        runs = await database_sync_to_async(_collect_due_dreaming_runs, thread_sensitive=False)(enrolled)
    logger.info("dreaming coordinator: due runs", count=len(runs))
    return FetchDueDreamingRunsOutput(due_runs=runs)


@activity.defn
@scoped_temporal()
async def stamp_dreaming_runs_activity(stamp_input: StampDreamingRunsInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_stamp_dispatched, thread_sensitive=False)(stamp_input.dispatched)


@workflow.defn(name="run-dreaming-coordinator")
class DreamingCoordinatorWorkflow:
    """Nightly coordinator: enrolls signals teams and fans out one dreaming run per team.

    Fire-and-forget dispatch (ABANDON child close policy + deterministic per-tick ids), so
    the coordinator's lifetime is seconds and the nightly schedule's SKIP overlap never
    collapses ticks. `last_run_at` is stamped only after dispatch so a fan-out failure
    re-dispatches the next night rather than silently skipping a team.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DreamingCoordinatorInput:
        if not inputs:
            return DreamingCoordinatorInput()
        return DreamingCoordinatorInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, _input: DreamingCoordinatorInput) -> DreamingCoordinatorOutput:
        fetched = await workflow.execute_activity(
            fetch_due_dreaming_runs_activity,
            FetchDueDreamingRunsInput(),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        due_runs = fetched.due_runs
        if not due_runs:
            return DreamingCoordinatorOutput(0, 0, 0)

        tick_id = workflow.info().workflow_id
        started = 0
        skipped = 0
        dispatched: list[DreamingTeamRun] = []
        for run in due_runs:
            if await _start_dreaming_child(run, tick_id):
                started += 1
            else:
                skipped += 1
            dispatched.append(run)

        await workflow.execute_activity(
            stamp_dreaming_runs_activity,
            StampDreamingRunsInput(dispatched=dispatched),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        return DreamingCoordinatorOutput(
            due_count=len(due_runs),
            started_count=started,
            skipped_count=skipped,
        )


async def _start_dreaming_child(run: DreamingTeamRun, tick_id: str) -> bool:
    """Fire-and-forget child dispatch. Returns True if started, False if dedupe-skipped."""
    from products.signals.backend.temporal.dreaming.workflow import RunDreamingInput, RunDreamingWorkflow

    child_id = f"run-dreaming-{run.team_id}-{tick_id}"
    try:
        await workflow.start_child_workflow(
            RunDreamingWorkflow.run,
            RunDreamingInput(team_id=run.team_id),
            id=child_id,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        return True
    except WorkflowAlreadyStartedError:
        workflow.logger.info("dreaming coordinator: child already started, skipping", extra={"team_id": run.team_id})
        return False
