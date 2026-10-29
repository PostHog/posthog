from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0127_replayobservationfeedimpression"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("status", "succeeded"), ("watch_rank__isnull", False)),
                fields=["scanner", "created_at"],
                include=["id", "team", "completed_at", "watch_rank", "distinct_id", "session_id"],
                name="rlo_scanner_ranked_idx",
            ),
        ),
    ]
