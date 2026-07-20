"""Hourly sweep that settles pending post-merge fix verifications.

The tasks GitHub webhook records a pending `SignalFixVerification` when a merged PR
resolves a report (see `fix_verification.py`); this workflow is what actually settles
those claims against reality — recurrence means REGRESSED, quiet-through-soak means
VERIFIED. Hourly because outcomes gate memory write-back and inbox context, not
anything latency-sensitive.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings

import structlog
from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.signals.backend.fix_verification import evaluate_pending_fix_verifications

logger = structlog.get_logger(__name__)

SWEEP_INTERVAL_MINUTES = 60

FIX_VERIFICATION_SWEEP_SCHEDULE_ID = "signals-fix-verification-sweep-schedule"
FIX_VERIFICATION_SWEEP_WORKFLOW_NAME = "signals-fix-verification-sweep"


@dataclass
class FixVerificationSweepWorkflowInput:
    """Placeholder input for forward-compat (e.g. future dry-run / team filters)."""

    pass


@dataclass
class FixVerificationSweepWorkflowOutput:
    checked: int
    verified: int
    regressed: int
    inconclusive: int


@activity.defn
async def sweep_fix_verifications_activity(
    _input: FixVerificationSweepWorkflowInput,
) -> FixVerificationSweepWorkflowOutput:
    async with Heartbeater():
        stats = await database_sync_to_async(evaluate_pending_fix_verifications, thread_sensitive=False)()
        logger.info(
            "signals_fix_verification_sweep_completed",
            checked=stats.checked,
            verified=stats.verified,
            regressed=stats.regressed,
            inconclusive=stats.inconclusive,
        )
        return FixVerificationSweepWorkflowOutput(
            checked=stats.checked,
            verified=stats.verified,
            regressed=stats.regressed,
            inconclusive=stats.inconclusive,
        )


@workflow.defn(name=FIX_VERIFICATION_SWEEP_WORKFLOW_NAME)
class SignalFixVerificationSweepWorkflow:
    """One activity per tick; the per-sweep row cap inside it bounds the tick's work."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> FixVerificationSweepWorkflowInput:
        if not inputs:
            return FixVerificationSweepWorkflowInput()
        loaded = json.loads(inputs[0])
        return FixVerificationSweepWorkflowInput(**loaded)

    @workflow.run
    async def run(self, input: FixVerificationSweepWorkflowInput) -> FixVerificationSweepWorkflowOutput:
        return await workflow.execute_activity(
            sweep_fix_verifications_activity,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


async def create_signals_fix_verification_sweep_schedule(client: Client) -> None:
    """Create or update the hourly sweep schedule.

    Runs on the shared signals task queue (see `create_signals_scout_coordinator_schedule`
    for the queue rationale). SKIP overlap: a slow sweep just defers the next tick — the
    due-set is recomputed from the DB every tick, so nothing is lost.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            FIX_VERIFICATION_SWEEP_WORKFLOW_NAME,
            asdict(FixVerificationSweepWorkflowInput()),
            id=FIX_VERIFICATION_SWEEP_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=SWEEP_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, FIX_VERIFICATION_SWEEP_SCHEDULE_ID):
        await a_update_schedule(client, FIX_VERIFICATION_SWEEP_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            FIX_VERIFICATION_SWEEP_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )
