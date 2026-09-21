from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0025_issue_state_updated_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(
                condition=models.Q(state_updated_at__isnull=False),
                fields=["team", "-state_updated_at"],
                name="et_issue_team_state_idx",
            ),
        ),
    ]
