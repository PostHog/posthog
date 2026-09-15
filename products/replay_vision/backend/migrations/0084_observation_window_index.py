from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction; replay_observation is large in production.
    atomic = False

    dependencies = [
        ("replay_vision", "0083_visionalertconfiguration_visionalertevent_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("status", "succeeded")),
                fields=["scanner", "completed_at"],
                name="rlo_scanner_completed_idx",
            ),
        ),
    ]
