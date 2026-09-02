from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the build takes no ACCESS EXCLUSIVE lock on the mapping table.
    # Concurrent builds can't run in a transaction, so this migration is non-atomic.
    atomic = False

    dependencies = [
        ("slack_app", "0011_slacksettings_permission_modes"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="slackthreadtaskmapping",
            index=models.Index(
                fields=["slack_workspace_id", "created_at"],
                include=["team_id"],
                name="slack_thr_map_ws_created_idx",
            ),
        ),
    ]
