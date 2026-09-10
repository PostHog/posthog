from django.db import migrations, models
from django.db.models.functions import Coalesce

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
                models.F("team"),
                models.F("next_check_at").asc(nulls_first=True),
                models.F("id"),
                name="logs_alert_team_due_sched",
                condition=models.Q(enabled=True) & ~models.Q(state="broken"),
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="logsalertconfiguration",
            index=models.Index(
                Coalesce("next_check_at", "updated_at", "created_at"),
                models.F("id"),
                name="logs_alert_due_schedule",
                condition=models.Q(enabled=True) & ~models.Q(state="broken"),
            ),
        ),
    ]
