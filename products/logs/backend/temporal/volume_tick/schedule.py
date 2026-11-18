"""Schedule registration for the logs volume tick workflow."""

from temporalio.client import Client

from posthog.temporal.common.schedule import a_pause_schedule, a_schedule_exists

from products.logs.backend.temporal.volume_tick.constants import SCHEDULE_ID


async def disable_logs_volume_tick_schedule(client: Client) -> None:
    """Disabled: pause the logs volume tick schedule. The worker is no longer deployed, so ticks would never be picked up."""
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_pause_schedule(client, SCHEDULE_ID, note="Disabled: temporal-worker-logs-volume-tick is not deployed")
