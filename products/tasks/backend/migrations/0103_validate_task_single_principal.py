from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0102_task_single_principal_constraint"),
    ]

    operations = [
        ValidateConstraint(model_name="task", name="posthog_task_single_principal"),
    ]
