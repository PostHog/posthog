from django.db import migrations


class Migration(migrations.Migration):
    """Drop two of the three retired session-summarization tables.

    Phase 2 of the two-phase table drop (safe-django-migrations.md, "Dropping Tables"). 0002 removed
    the models from Django state only, so the tables, their indexes and their foreign keys on
    posthog_team stayed in Postgres with no reader or writer left.

    `ee_single_session_summary` stays for now: `nodejs/src/session-replay/recording-api/
    recording-service.ts` still deletes from it when a recording is deleted.

    The reverse is a no-op rather than a bogus CREATE TABLE.
    """

    dependencies = [
        ("replay", "0003_drop_exception_event_ids_gin_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql='DROP TABLE IF EXISTS "ee_group_session_summary";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='DROP TABLE IF EXISTS "ee_teamsessionsummariesconfig";',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
