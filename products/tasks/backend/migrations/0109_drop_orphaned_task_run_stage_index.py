from django.db import migrations

from posthog.migration_helpers.concurrent_index import DropIndexConcurrently


class Migration(migrations.Migration):
    """Drop the orphaned index left by migration 0015.

    Migration 0015 removed the workflow-stage model and the field
    `TaskRun.current_stage` from Django state, but its database half only
    dropped the foreign-key constraint. The auto-created index on the
    `current_stage_id` column survived, and no code path can reach it.

    The drop runs concurrently so it never blocks reads or writes on
    `posthog_task_run`. The column itself goes in migration 0110.
    """

    atomic = False

    dependencies = [
        ("tasks", "0108_channel_auto_archive_after_days"),
    ]

    operations = [
        DropIndexConcurrently(
            index_name="posthog_task_run_current_stage_id_2f86e8d0",
            table_name="posthog_task_run",
            columns="(current_stage_id)",
        ),
    ]
