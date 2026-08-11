from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0063_alter_replayobservation_triggered_by_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                fields=["backfill"],
                name="rlo_backfill_idx",
                condition=models.Q(backfill__isnull=False),
            ),
        ),
    ]
