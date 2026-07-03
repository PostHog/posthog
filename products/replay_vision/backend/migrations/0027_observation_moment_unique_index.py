from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    """Build the (scanner, session_id, moment_key) unique index concurrently; 0028 promotes it to a constraint."""

    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("replay_vision", "0026_moments_scope_fields"),
    ]

    operations = [
        CreateIndexConcurrently(
            index_name="replay_observation_unique_scanner_session_moment",
            table_name="replay_vision_replayobservation",
            columns='("scanner_id", "session_id", "moment_key")',
            unique=True,
        ),
    ]
