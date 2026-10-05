from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0041_errortrackingalertdestination_consecutive_failures_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(fields=["team", "-id"], name="et_issue_team_id_desc_idx"),
        ),
    ]
