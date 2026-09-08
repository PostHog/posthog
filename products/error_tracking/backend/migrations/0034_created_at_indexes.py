from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0033_drop_superseded_fingerprint_constraint"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissue",
            index=models.Index(fields=["team", "-created_at"], name="et_issue_team_created_at_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="errortrackingissuefingerprintv2",
            index=models.Index(fields=["team", "created_at"], name="et_fp_team_created_at_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="errortrackingissuefingerprintv2",
            index=models.Index(fields=["team", "issue", "created_at"], name="et_fp_team_issue_created_idx"),
        ),
    ]
