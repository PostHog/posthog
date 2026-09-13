from django.db import migrations


class Migration(migrations.Migration):
    """Phase 2 of the two-phase drop for the retired session-summarization tables.

    0002 removed the models from Django state only, so the tables and their foreign keys stayed in
    Postgres. `ee_single_session_summary` is not dropped: recording deletion in
    nodejs/src/session-replay/recording-api/recording-service.ts still writes to it. Its foreign
    keys go anyway, because Django can no longer see the model to cascade or null the columns, so a
    leftover row blocks deletion of the team or the user at COMMIT.

    Every statement takes ACCESS EXCLUSIVE on posthog_team or posthog_user, so lock_timeout bounds
    how long queries queue behind it. The drops stay in separate operations because the risk
    analyzer validates only the first DROP TABLE per statement. Constraint names carry a generated
    hash, so the last operation reads them from the catalog instead of guessing.
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
        migrations.RunSQL(
            sql="""
            SET LOCAL lock_timeout = '5s';
            DO $$
            DECLARE fk record;
            BEGIN
                FOR fk IN
                    SELECT con.conname
                    FROM pg_constraint con
                    JOIN pg_class src ON src.oid = con.conrelid
                    WHERE con.contype = 'f'
                      AND src.relname = 'ee_single_session_summary'
                LOOP
                    EXECUTE format(
                        'ALTER TABLE ee_single_session_summary DROP CONSTRAINT IF EXISTS %I',
                        fk.conname
                    );
                END LOOP;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
