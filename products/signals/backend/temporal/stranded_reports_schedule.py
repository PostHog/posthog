"""Schedule registration for the stranded signal report reconciler."""

from __future__ import annotations

from dataclasses import asdict

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.signals.backend.temporal.stranded_reports import (
    SCHEDULE_ID,
    SCHEDULE_INTERVAL,
    WORKFLOW_NAME,
    StrandedReportReconcilerInput,
)


async def create_signals_stranded_report_reconciler_schedule(client: Client) -> None:
    """Create or update the schedule that fails signal reports stranded in `in_progress`.

    Same task queue and overlap posture as the scout coordinator. One tick is bounded by the per-tick
    report cap, and `execution_timeout` caps it at one interval so a tick that hangs on Temporal
    describes cannot starve the next one under `SKIP`.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            asdict(StrandedReportReconcilerInput()),
            id=SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=SCHEDULE_INTERVAL,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
