from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0161_task_run_log_format"),
    ]

    operations = [
        ValidateConstraint(model_name="taskrun", name="posthog_task_run_log_chunk_count_check"),
    ]
