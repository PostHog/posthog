from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the index build takes no ACCESS EXCLUSIVE lock on posthog_task_run.
    # Concurrent builds can't run in a transaction, so this migration is non-atomic.
    atomic = False

    dependencies = [
        ("tasks", "0083_taskcommentactivity"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="awaiting_input_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "When the run last raised a permission request that nobody has answered yet. Null once "
                    "a response is sent. Only meaningful while the run is queued or in progress."
                ),
                null=True,
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                condition=models.Q(("awaiting_input_at__isnull", False)),
                fields=["team", "task"],
                name="task_run_awaiting_input_idx",
            ),
        ),
    ]
