from posthog.temporal.health_checks.rollups.store import delete_rollup_rows_for_teams

from ..models.health_rollups import EventsHealthDaily, HostProxyDaily


def delete_health_rollups_for_teams(team_ids: list[int]) -> None:
    """Remove the web health rollup rows of the given environments. Called from team deletion."""
    delete_rollup_rows_for_teams(EventsHealthDaily, team_ids)
    delete_rollup_rows_for_teams(HostProxyDaily, team_ids)
