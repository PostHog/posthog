from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("slack_app", "0025_slack_daily_focus"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="slacksettings",
            index=models.Index(
                condition=models.Q(("daily_focus_next_run_at__isnull", False)),
                fields=["daily_focus_next_run_at"],
                name="slack_settings_daily_focus_idx",
            ),
        ),
    ]
