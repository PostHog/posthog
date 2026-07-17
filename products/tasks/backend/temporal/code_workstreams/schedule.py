from dataclasses import asdict
from datetime import timedelta

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

from products.tasks.backend.temporal.code_workstreams.workflow import EvaluateCodeWorkstreamsInput

SCHEDULE_ID = "evaluate-code-workstreams-schedule"


async def create_evaluate_code_workstreams_schedule(client: Client):
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "evaluate-code-workstreams",
            asdict(EvaluateCodeWorkstreamsInput()),
            id="evaluate-code-workstreams",
            task_queue=settings.TASKS_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=3))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
