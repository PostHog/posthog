from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0043_auto_resolve_safety"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(
                condition=models.Q(("auto_resolve_sync_requested_at__isnull", False)),
                fields=["team", "id"],
                name="et_issue_pending_sync_idx",
            ),
        ),
    ]
