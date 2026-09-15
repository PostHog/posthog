from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0037_untrack_assignment_user_group"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(fields=["team", "-created_at", "-id"], name="et_issue_team_created_idx"),
        ),
    ]
