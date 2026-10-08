from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction; replay_observation is large in production.
    atomic = False

    dependencies = [
        ("replay_vision", "0097_replayobservation_media_render_attempted_at_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("status", "succeeded")),
                fields=["-created_at"],
                name="rlo_succeeded_created_idx",
            ),
        ),
    ]
