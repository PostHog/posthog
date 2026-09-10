from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("logs", "0025_alter_logsalertconfiguration_team_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="logsalertconfiguration",
            index=models.Index(
                fields=["team", "next_check_at", "id"],
                name="logs_alert_team_due_sched",
                condition=models.Q(enabled=True),
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="logsalertconfiguration",
            index=models.Index(
                fields=["next_check_at", "id"],
                name="logs_alert_due_schedule",
                condition=models.Q(enabled=True),
            ),
        ),
    ]
