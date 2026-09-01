from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction; replay_observation is large in production.
    atomic = False

    dependencies = [
        ("replay_vision", "0086_replayobservation_rlo_team_session_idx"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="replayobservation",
            name="rlo_workflow_id_idx",
        ),
    ]
