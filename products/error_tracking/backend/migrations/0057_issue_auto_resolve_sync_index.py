from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("error_tracking", "0056_issue_auto_resolve")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(
                fields=["team", "id"],
                name="et_issue_auto_resolve_sync_idx",
                condition=models.Q(auto_resolve_sync_requested_at__isnull=False),
            ),
        ),
    ]
