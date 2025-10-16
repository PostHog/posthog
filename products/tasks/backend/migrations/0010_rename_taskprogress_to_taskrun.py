# Manual migration to rename TaskProgress to TaskRun
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0009_task_created_by"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="TaskProgress",
            new_name="TaskRun",
        ),
    ]
