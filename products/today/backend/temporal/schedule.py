"""Removes the retired briefing schedule. Its workflow is no longer registered, so each run would fail."""

from temporalio.client import Client

from posthog.temporal.common.schedule import a_delete_schedule, a_schedule_exists

_SCHEDULE_ID = "today-briefing-scheduler"


async def delete_today_briefing_schedule(client: Client) -> None:
    if await a_schedule_exists(client, _SCHEDULE_ID):
        await a_delete_schedule(client, _SCHEDULE_ID)
