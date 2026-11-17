from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0054_errortrackingsettings_ai_issue_summaries_enabled")
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissuechange",
            index=models.Index(
                fields=["team", "created_at"], name="idx_et_issue_change_team_time"
            ),
        ),
    ]
