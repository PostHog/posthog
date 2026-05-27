from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0032_task_archived_archived_at"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["archived"], name="posthog_task_archived_idx"),
        ),
    ]
