from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0125_taskrun_scheduled_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["scheduled_at", "id"],
                name="task_run_scheduled_due_idx",
                condition=models.Q(status="not_started", environment="cloud", scheduled_at__isnull=False),
            ),
        ),
    ]
