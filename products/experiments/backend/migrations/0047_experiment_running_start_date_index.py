from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("experiments", "0046_untrack_legacy_recalculation_time"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="experiment",
            index=models.Index(
                condition=models.Q(("deleted", False), ("status", "running")),
                fields=["start_date"],
                name="posthog_exp_running_start_idx",
            ),
        ),
    ]
