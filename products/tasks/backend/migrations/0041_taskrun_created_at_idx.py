from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False

    dependencies = [
        ("tasks", "0040_alter_task_origin_product"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(fields=["created_at"], name="task_run_created_at_idx"),
        ),
    ]
