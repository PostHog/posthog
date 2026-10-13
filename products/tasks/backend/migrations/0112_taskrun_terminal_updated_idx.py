from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0111_taskrun_status_env_origin_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["updated_at"],
                include=["status", "environment", "origin_product"],
                name="task_run_terminal_updated_idx",
                condition=models.Q(status__in=["completed", "failed", "cancelled"]),
            ),
        ),
    ]
