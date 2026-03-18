from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0018_alter_taskrun_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="taskrun",
                    name="log_storage_path",
                ),
            ],
            database_operations=[],
        ),
    ]
