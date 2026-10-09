from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0126_taskrun_scheduled_due_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskworkflowdispatch",
            index=models.Index(
                fields=["next_attempt_at", "created_at"],
                name="twd_pending_due_order",
                condition=models.Q(status="pending"),
            ),
        ),
    ]
