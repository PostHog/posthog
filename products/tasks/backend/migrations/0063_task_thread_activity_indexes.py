from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0062_sandbox_custom_image_base_reference"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskthreadmessage",
            index=models.Index(
                fields=["team", "author", "created_at"],
                name="task_thread_author_created_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="taskthreadmessage",
            index=models.Index(
                fields=["team", "task", "created_at"],
                name="task_thread_turn_complete_idx",
                condition=models.Q(event="turn_complete"),
            ),
        ),
    ]
