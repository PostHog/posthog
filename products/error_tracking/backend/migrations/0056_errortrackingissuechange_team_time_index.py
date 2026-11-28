from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("error_tracking", "0055_errortrackingissuetagrule_color")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissuechange",
            index=models.Index(fields=["team", "created_at"], name="idx_et_issue_change_team_time"),
        ),
    ]
