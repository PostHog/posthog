from django.db import migrations


class Migration(migrations.Migration):
    # Phase 2 of the table drop that migration 0015 started (see safe-django-migrations.md
    # "Dropping Tables"). 0015 deleted these three models from Django's model state and dropped
    # their foreign key constraints, but left the tables in Postgres.
    #
    # This is a separate migration from 0116 on purpose. The CI migration risk analyzer blocks a
    # migration that holds an ALTER TABLE next to any other operation, and it reads only the
    # first drop in a RunSQL, so merging the two would leave these table drops unchecked.
    #
    # The pooled connection sets no lock_timeout, so without SET LOCAL a stray lock on one of
    # these tables would hold the deploy open.

    dependencies = [
        ("tasks", "0116_drop_orphaned_workflow_columns"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                SET LOCAL lock_timeout = '5s';
                DROP TABLE IF EXISTS posthog_workflow_stage;
                DROP TABLE IF EXISTS posthog_task_workflow;
                DROP TABLE IF EXISTS posthog_task_progress;
            """,
            # The models are gone from Django state, so recreating empty tables would restore
            # only the orphans.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
