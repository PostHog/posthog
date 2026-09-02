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

from products.review_hog.backend.temporal.outcomes_types import (
    CLASSIFY_FINDING_OUTCOMES_WORKFLOW,
    ClassifyFindingOutcomesInputs,
)

SCHEDULE_ID = "review-hog-finding-outcomes-schedule"
# Hourly is well within the 30-day merged-PR lookback, so a merge is never missed between runs; SKIP
# overlap means a long sweep is never doubled up on.
SCHEDULE_INTERVAL = timedelta(hours=1)


async def create_review_hog_finding_outcomes_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CLASSIFY_FINDING_OUTCOMES_WORKFLOW,
            ClassifyFindingOutcomesInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
