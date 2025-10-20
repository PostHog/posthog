# Generated migration to remove redundant status field

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0003_simplify_workflow_remove_transitions"),
    ]

    operations = [
        # Remove the status field from Task model
        migrations.RemoveField(
            model_name="task",
            name="status",
        ),
    ]
