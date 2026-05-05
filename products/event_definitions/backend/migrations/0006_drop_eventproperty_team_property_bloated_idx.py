from django.db import migrations


class Migration(migrations.Migration):
    """Drop posthog_eve_team_id_26dbfb_idx — bloated 271 GB twin of r32khd9s (52 GB natural).

    Same definition (team_id, property) as posthog_eventproperty_team_id_and_property_r32khd9s
    (created via raw SQL in migration 0411). 12x bloat ratio. 0 prod scans across us, eu, dev.
    Replay/cleanup queries already prefer r32khd9s — verified in prod-us EXPLAIN ANALYZE (May 2026).
    """

    atomic = False

    dependencies = [
        ("event_definitions", "0005_eventdefinition_rename_promoted_to_primary"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="eventproperty",
                    name="posthog_eve_team_id_26dbfb_idx",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_eve_team_id_26dbfb_idx",
                    reverse_sql="""
                        CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_eve_team_id_26dbfb_idx
                        ON posthog_eventproperty (team_id, property)
                    """,
                ),
            ],
        ),
    ]
