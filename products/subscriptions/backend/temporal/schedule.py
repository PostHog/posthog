from dataclasses import asdict

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.subscriptions.backend.temporal.types import ScheduleAllSubscriptionsWorkflowInputs


async def create_schedule_all_subscriptions_schedule(client: Client) -> None:
    """Create or update the schedule for the ScheduleAllSubscriptionsWorkflow.

    This schedule runs twice an hour, shortly before each supported delivery slot.
    """
    schedule_all_subscriptions_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "schedule-all-subscriptions",
            asdict(ScheduleAllSubscriptionsWorkflowInputs()),
            id="schedule-all-subscriptions-schedule",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["25,55 * * * *"]),  # Run shortly before :30 and :00 deliveries
        # ALLOW_ALL: if a previous run is still executing, start the new one anyway.
        # Deterministic subscription child IDs prevent duplicate starts while a child is open.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
    )

    if await a_schedule_exists(client, "schedule-all-subscriptions-schedule"):
        await a_update_schedule(client, "schedule-all-subscriptions-schedule", schedule_all_subscriptions_schedule)
    else:
        await a_create_schedule(
            client,
            "schedule-all-subscriptions-schedule",
            schedule_all_subscriptions_schedule,
            trigger_immediately=False,
        )
