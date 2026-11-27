from dataclasses import dataclass

TICK_FLAG_WINDOWS_WORKFLOW = "feature-flags-tick-flag-windows"


@dataclass(frozen=True)
class TickFlagWindowsInputs:
    """The input of the scheduled tick. The tick reads the teams from the watch flag."""


@dataclass(frozen=True)
class TickTeamFlagWindowsInputs:
    team_id: int
