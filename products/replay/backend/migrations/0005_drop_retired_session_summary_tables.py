from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Phase 2 of the two-phase drop for the retired session-summarization tables.

    0002 removed the models from Django state only. `ee_single_session_summary` stays because
    nodejs/src/session-replay/recording-api/recording-service.ts still deletes from it, but its
    last foreign key goes: Django cannot cascade into a table it no longer sees, so a leftover row
    fails the team delete at COMMIT. 0004 already dropped the keys to posthog_user.

    The drops stay in separate operations because the risk analyzer validates only the first
    DROP TABLE per statement.
    """

    dependencies = [
        ("replay", "0004_drop_orphaned_session_summary_user_fks"),
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
        DropForeignKey("ee_single_session_summary", to_table="posthog_team"),
    ]
