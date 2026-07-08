from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0029_replayobservationusage_team_id"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservationusage",
            index=models.Index(fields=["created_at", "team_id"], name="rlou_created_team_idx"),
        ),
    ]
