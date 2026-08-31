from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("tasks", "0106_sandboxsession_sandbox_backend")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        DO $$
                        DECLARE r RECORD;
                        BEGIN
                            FOR r IN (
                                SELECT conname FROM pg_constraint
                                WHERE conrelid = 'posthog_code_invite'::regclass
                                AND contype = 'f'
                            ) LOOP
                                EXECUTE format(
                                    'ALTER TABLE posthog_code_invite DROP CONSTRAINT %I', r.conname
                                );
                            END LOOP;
                        EXCEPTION WHEN undefined_table THEN NULL;
                        END $$;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql="""
                        DO $$
                        DECLARE r RECORD;
                        BEGIN
                            FOR r IN (
                                SELECT conname FROM pg_constraint
                                WHERE conrelid = 'posthog_code_invite_redemption'::regclass
                                AND contype = 'f'
                            ) LOOP
                                EXECUTE format(
                                    'ALTER TABLE posthog_code_invite_redemption DROP CONSTRAINT %I', r.conname
                                );
                            END LOOP;
                        EXCEPTION WHEN undefined_table THEN NULL;
                        END $$;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.DeleteModel(name="CodeInviteRedemption"),
                migrations.DeleteModel(name="CodeInvite"),
            ],
        ),
    ]
