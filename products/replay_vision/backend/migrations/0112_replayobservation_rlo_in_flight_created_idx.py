from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building the partial index doesn't take an ACCESS EXCLUSIVE lock on
    # replay_observation. Concurrent builds can't run in a transaction, so this is non-atomic.
    atomic = False

    dependencies = [
        ("replay_vision", "0111_replayobservation_session_geoip"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("status__in", ("pending", "running"))),
                fields=["created_at"],
                name="rlo_in_flight_created_idx",
            ),
        ),
    ]
