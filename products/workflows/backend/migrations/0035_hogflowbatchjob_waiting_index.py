from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("workflows", "0034_teamworkflowsconfig_replay_vision_scan_limits"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="hogflowbatchjob",
            index=models.Index(
                condition=models.Q(("status", "waiting")),
                fields=["created_at"],
                name="hogflowbatchjob_waiting_idx",
            ),
        ),
    ]
