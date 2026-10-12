from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy

from posthog.scheduling.jitter import deterministic_offset
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.managed_warehouse.backend.temporal.external_table_registration_workflow import (
    ExternalTableRegistrationInputs,
)

if TYPE_CHECKING:
    from temporalio.client import Client


async def configure_external_table_schedule(
    client: Client, team_id: int, table_id: UUID, interval: dt.timedelta, *, trigger_immediately: bool = False
) -> str:
    if interval < dt.timedelta(minutes=5):
        raise ValueError("The refresh interval must be at least five minutes")
    schedule_id = f"ducklake-register-external-table-{team_id}-{table_id}"
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "ducklake-register.external-table",
            ExternalTableRegistrationInputs(team_id=team_id, table_id=table_id),
            id=schedule_id,
            task_queue=settings.DUCKLAKE_TASK_QUEUE,
            execution_timeout=dt.timedelta(hours=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=interval,
                    offset=deterministic_offset(
                        schedule_id, interval - dt.timedelta(minutes=1), floor=dt.timedelta(minutes=1)
                    ),
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule)
        if trigger_immediately:
            await client.get_schedule_handle(schedule_id).trigger(overlap=ScheduleOverlapPolicy.SKIP)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=True)
    return schedule_id
