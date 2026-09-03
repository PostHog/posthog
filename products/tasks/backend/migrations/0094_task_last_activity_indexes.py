from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("tasks", "0093_task_last_activity_default")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["team", "-last_activity_at", "-id"], name="posthog_task_team_activity_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["channel", "-last_activity_at"], name="posthog_task_chan_activity_idx"),
        ),
    ]
