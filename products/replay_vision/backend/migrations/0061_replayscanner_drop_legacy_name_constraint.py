from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    """Cleanup, once the replacement indexes from 0060 exist."""

    dependencies = [
        ("replay_vision", "0060_replayscanner_origin_indexes"),
    ]

    operations = [
        # Superseded by the partial index built in 0060. Dropped only after its replacement exists, so
        # team name uniqueness is never unenforced.
        migrations.RemoveConstraint(
            model_name="replayscanner",
            name="replay_scanner_unique_team_name",
        ),
        # Non-blocking: VALIDATE takes SHARE UPDATE EXCLUSIVE, so reads and writes continue.
        ValidateConstraint(
            model_name="replayscanner",
            name="replay_scanner_inline_key_matches_origin",
        ),
    ]
