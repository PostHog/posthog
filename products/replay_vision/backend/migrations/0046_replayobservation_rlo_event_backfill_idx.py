from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building the partial index doesn't take an ACCESS EXCLUSIVE lock on
    # replay_observation. Concurrent builds can't run in a transaction, so this is non-atomic.
    atomic = False

    dependencies = [
        ("replay_vision", "0045_replayobservation_event_emitted_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("status", "succeeded"), ("event_emitted_at__isnull", True)),
                fields=["completed_at"],
                name="rlo_event_backfill_idx",
            ),
        ),
    ]
