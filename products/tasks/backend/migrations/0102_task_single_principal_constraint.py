from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0101_task_system_principal"),
    ]

    operations = [
        AddConstraintNotValid(
            model_name="task",
            constraint=models.CheckConstraint(
                condition=models.Q(created_by__isnull=True) | models.Q(system_principal__isnull=True),
                name="posthog_task_single_principal",
            ),
        ),
    ]
