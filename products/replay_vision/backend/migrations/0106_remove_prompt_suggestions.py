from django.db import migrations

from posthog.migration_helpers import DropForeignKey
from posthog.migration_helpers.untrack_field import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0105_alter_replayobservation_error_reason"),
    ]

    operations = [
        untrack_field("replayscanner", "feedback_themes"),
        # The table stays until a later migration drops it with SafeDropTable. Its team and user keys were
        # created with db_constraint=False, but the scanner key is real: once Django stops cascading into the
        # table, a scanner delete would fail at COMMIT, so that constraint goes now.
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="ReplayScannerPromptSuggestion")],
            database_operations=[
                DropForeignKey("replay_vision_replayscannerpromptsuggestion", column="scanner_id"),
            ],
        ),
    ]
