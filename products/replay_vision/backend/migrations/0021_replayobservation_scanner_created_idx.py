from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False

    dependencies = [
        ("replay_vision", "0020_replayobservation_recording_subject_email"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(fields=["scanner", "created_at"], name="rlo_scanner_created_idx"),
        ),
    ]
