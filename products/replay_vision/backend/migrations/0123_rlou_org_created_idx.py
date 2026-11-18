from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0122_replayvisionorgadmissionbudget"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservationusage",
            index=models.Index(fields=["organization", "created_at"], name="rlou_org_created_idx"),
        ),
    ]
