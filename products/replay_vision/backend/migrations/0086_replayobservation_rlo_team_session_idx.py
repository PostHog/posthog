from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction; replay_observation is large in production.
    atomic = False

    dependencies = [
        ("replay_vision", "0085_alter_replayobservation_error_reason"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(fields=["team", "session_id"], name="rlo_team_session_idx"),
        ),
    ]
