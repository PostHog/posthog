from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # Required for AddIndexConcurrently

    dependencies = [
        ("tasks", "0045_channel_task_channel_taskthreadmessage"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["channel", "-created_at"], name="posthog_task_channel_feed_idx"),
        ),
    ]
