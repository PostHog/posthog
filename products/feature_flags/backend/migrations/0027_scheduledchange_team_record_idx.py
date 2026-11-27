from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("feature_flags", "0026_squash_2026_11_02_schema_addons"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="scheduledchange",
            index=models.Index(fields=["team", "model_name", "record_id"], name="sched_change_team_record_idx"),
        ),
    ]
