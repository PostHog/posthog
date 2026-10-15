"""Cleanup for the retired daily briefing, whose table outlives its model until a later migration drops it."""

from django.db import connection


def delete_for_teams(team_ids: list[int]) -> None:
    """Briefing rows hold LLM text about a person's reports, so a deleted team must not leave them behind."""
    if not team_ids:
        return
    with connection.cursor() as cursor:
        # A schema built from models instead of migrations has no table. Remove this module with the table drop.
        cursor.execute("SELECT to_regclass('today_dailybriefing') IS NOT NULL")
        if cursor.fetchone()[0]:
            cursor.execute("DELETE FROM today_dailybriefing WHERE team_id = ANY(%s)", [team_ids])
