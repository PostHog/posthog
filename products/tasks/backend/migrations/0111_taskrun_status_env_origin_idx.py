from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building the index does not take an ACCESS EXCLUSIVE lock on
    # posthog_task_run. Concurrent builds cannot run in a transaction, so the migration
    # is non-atomic.
    atomic = False

    dependencies = [
        ("tasks", "0110_backfill_taskrun_origin_product"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["status", "environment", "origin_product"],
                name="task_run_status_env_origin_idx",
            ),
        ),
    ]
