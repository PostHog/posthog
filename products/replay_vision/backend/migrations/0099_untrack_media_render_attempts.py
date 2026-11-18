from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently, untrack_field


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction; replay_observation is large in production.
    atomic = False

    dependencies = [
        ("replay_vision", "0098_replayobservation_rlo_succeeded_created_idx"),
    ]

    operations = [
        # The columns stay: media_render_attempts is NOT NULL, and its database default of 0 fills it once Django stops writing it.
        untrack_field("replayobservation", "media_render_attempts", "media_render_attempted_at"),
        SafeRemoveIndexConcurrently(
            model_name="replayobservation",
            name="rlo_succeeded_created_idx",
        ),
    ]
