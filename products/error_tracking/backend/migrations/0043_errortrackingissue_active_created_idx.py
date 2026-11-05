from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """The index behind the weekly digest's new-issues read, built without locking writes out of the table."""

    atomic = False

    dependencies = [
        ("error_tracking", "0042_errortrackingissuechange"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(
                condition=models.Q(("status", "active")),
                fields=["team", "-created_at"],
                name="et_issue_active_created_idx",
            ),
        ),
    ]
