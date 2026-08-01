from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0078_taskartifact_channel_alter_taskartifact_adapter_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskartifact",
            index=models.Index(
                fields=["team", "channel", "-updated_at"],
                name="task_artifact_team_chan_idx",
            ),
        ),
    ]
