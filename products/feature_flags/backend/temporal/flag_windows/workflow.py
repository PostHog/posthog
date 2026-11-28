"""The scheduled tick of the flag observation windows. It goes over the teams one by one, and a team that fails waits
for the next tick, so it never stops the others."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from products.feature_flags.backend.temporal.flag_windows.activities import (
    list_flag_window_teams_activity,
    tick_team_flag_windows_activity,
)
from products.feature_flags.backend.temporal.flag_windows.types import (
    TICK_FLAG_WINDOWS_WORKFLOW,
    TickFlagWindowsInputs,
    TickTeamFlagWindowsInputs,
)

_TIMEOUT = timedelta(minutes=5)
_RETRY = RetryPolicy(maximum_attempts=2)


@workflow.defn(name=TICK_FLAG_WINDOWS_WORKFLOW)
class TickFlagWindowsWorkflow:
    @workflow.run
    async def run(self, inputs: TickFlagWindowsInputs) -> int:
        team_ids: list[int] = await workflow.execute_activity(
            list_flag_window_teams_activity, start_to_close_timeout=_TIMEOUT, retry_policy=_RETRY
        )
        changed = 0
        for team_id in team_ids:
            try:
                changed += await workflow.execute_activity(
                    tick_team_flag_windows_activity,
                    TickTeamFlagWindowsInputs(team_id=team_id),
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=_RETRY,
                )
            except ActivityError:
                workflow.logger.warning("The flag windows tick failed for team %s", team_id)
        return changed
