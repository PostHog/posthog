from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for concurrent index creation

    dependencies = [
        ("tasks", "0045_channel_task_channel_taskthreadmessage"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["channel", "-created_at"], name="posthog_task_channel_feed_idx"),
        ),
    ]
