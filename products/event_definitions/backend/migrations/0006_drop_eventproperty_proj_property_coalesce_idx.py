from django.db import migrations


class Migration(migrations.Migration):
    """Drop posthog_eve_proj_id_26dbfb_idx — (coalesce(project_id, team_id), property), ~50 GB US / ~41 GB EU.

    Tier 1 follow-up to #57588. Provably unused:
    - 0 idx_scan on prod-us and prod-eu writers (pg_stat_user_indexes).
    - lastUsedAt also stale on read replicas (pganalyze).
    - No code path queries (coalesce, property) without an event filter — codebase audit clean.

    Coverage post-drop:
    - (coalesce, property) lookups with event filter → unique constraint
      posthog_event_property_unique_proj_event_property (coalesce, event, property).
    - (team, property) lookups → posthog_eventproperty_team_id_and_property_r32khd9s.
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
                    name="posthog_eve_proj_id_26dbfb_idx",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_eve_proj_id_26dbfb_idx",
                    reverse_sql="""
                        CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_eve_proj_id_26dbfb_idx
                        ON posthog_eventproperty (COALESCE(project_id, (team_id)::bigint), property)
                    """,
                ),
            ],
        ),
    ]
