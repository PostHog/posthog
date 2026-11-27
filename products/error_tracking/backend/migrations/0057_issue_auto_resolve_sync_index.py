from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("error_tracking", "0056_issue_auto_resolve")]

    operations = [
        AddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(
                fields=["team", "id"],
                name="et_issue_auto_resolve_sync_idx",
                condition=models.Q(auto_resolve_sync_requested_at__isnull=False),
            ),
        ),
    ]
