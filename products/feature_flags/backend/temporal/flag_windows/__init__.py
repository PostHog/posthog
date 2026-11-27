from products.feature_flags.backend.temporal.flag_windows.activities import (
    list_flag_window_teams_activity,
    tick_team_flag_windows_activity,
)
from products.feature_flags.backend.temporal.flag_windows.workflow import TickFlagWindowsWorkflow

WORKFLOWS = (TickFlagWindowsWorkflow,)
ACTIVITIES = (list_flag_window_teams_activity, tick_team_flag_windows_activity)
