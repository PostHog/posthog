from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0089_signalreportaction"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscoutrun",
            index=models.Index(
                fields=["team", "skill_name", "-created_at"],
                name="signal_scout_run_recent_idx",
            ),
        ),
    ]
