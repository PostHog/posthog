from django.db import migrations


class Migration(migrations.Migration):
    """Phase 2 of the two-phase drop for two retired session-summarization tables.

    0002 removed the models from Django state only, so the tables and their foreign keys on
    posthog_team stayed in Postgres. `ee_single_session_summary` is not dropped: recording deletion
    in nodejs/src/session-replay/recording-api/recording-service.ts still writes to it.

    Those foreign keys make DROP TABLE take ACCESS EXCLUSIVE on posthog_team and posthog_user, so
    lock_timeout bounds how long queries queue behind it. The drops stay in separate operations
    because the risk analyzer validates only the first DROP TABLE per statement.
    """

    dependencies = [
        ("replay", "0003_drop_exception_event_ids_gin_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            SET LOCAL lock_timeout = '5s';
            DROP TABLE IF EXISTS "ee_group_session_summary";
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
            SET LOCAL lock_timeout = '5s';
            DROP TABLE IF EXISTS "ee_teamsessionsummariesconfig";
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
