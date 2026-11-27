from django.utils import timezone

from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.feature_flags.backend.flag_windows.tick import tick_team, watched_team_ids
from products.feature_flags.backend.temporal.flag_windows.types import TickTeamFlagWindowsInputs


@activity.defn
@scoped_temporal()
@close_db_connections
async def list_flag_window_teams_activity() -> list[int]:
    return await database_sync_to_async(watched_team_ids, thread_sensitive=False)()


@activity.defn
@scoped_temporal()
@close_db_connections
async def tick_team_flag_windows_activity(inputs: TickTeamFlagWindowsInputs) -> int:
    """Returns the number of windows that the tick opened or closed."""
    tick = await database_sync_to_async(tick_team, thread_sensitive=False)(inputs.team_id, timezone.now())
    activity.logger.info(
        "Ticked the flag windows of team %s: %d opened, %d closed", inputs.team_id, tick.opened, tick.closed
    )
    return tick.opened + tick.closed
