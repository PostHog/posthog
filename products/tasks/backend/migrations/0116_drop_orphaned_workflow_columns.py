from django.db import migrations


class Migration(migrations.Migration):
    # Phase 2 of the column drop that migration 0015 started (see safe-django-migrations.md
    # "Dropping Columns"). 0015 removed these fields from Django's model state, but its
    # database_operations only dropped the foreign key constraints, so the columns stayed in
    # Postgres with no model behind them. Dropping each column also drops the dead btree index
    # on it: posthog_task_run_current_stage_id_2f86e8d0, posthog_task_current_stage_id_9f282f7b
    # and posthog_task_workflow_id_0b39c75b.
    #
    # posthog_task_run takes constant writes, so 5s keeps a lost lock race short. bin/migrate
    # retries, which the IF EXISTS guards make safe.
    #
    # Keep `log` first in the posthog_task_run statement. The CI migration risk analyzer reads
    # the first DROP COLUMN to find the matching state removal in 0015, and it cannot map a
    # foreign key column back to its field name (current_stage_id to current_stage).

    dependencies = [
        ("tasks", "0115_teamtasksconfig_usertasksconfig"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                SET LOCAL lock_timeout = '5s';
                ALTER TABLE posthog_task_run
                    DROP COLUMN IF EXISTS log,
                    DROP COLUMN IF EXISTS current_stage_id;
                ALTER TABLE posthog_task
                    DROP COLUMN IF EXISTS github_branch,
                    DROP COLUMN IF EXISTS github_pr_url,
                    DROP COLUMN IF EXISTS position,
                    DROP COLUMN IF EXISTS repository_config,
                    DROP COLUMN IF EXISTS current_stage_id,
                    DROP COLUMN IF EXISTS workflow_id;
            """,
            # Django state at 0115 already has no fields for these columns, so restoring them
            # would only put the orphans back.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
