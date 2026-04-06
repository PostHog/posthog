from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0026_task_signal_report_alter_task_origin_product"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["signal_report"], name="posthog_task_signal_report_idx"),
        ),
    ]
