from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the build takes no ACCESS EXCLUSIVE lock on the table.
    # Concurrent builds can't run in a transaction, so this migration is non-atomic.
    atomic = False

    dependencies = [
        ("replay_vision", "0058_delete_replayquotagrant"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayscannerpromptsuggestion",
            index=models.Index(
                fields=["team"],
                name="replay_sugg_running_idx",
                condition=models.Q(("evaluation__status", "running")),
            ),
        ),
    ]
