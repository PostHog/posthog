from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for concurrent index creation

    dependencies = [
        ("review_hog", "0015_reviewreport_status_comment_edited_at_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="reviewreport",
            index=models.Index(
                fields=["team", "-last_run_at"],
                name="reviewhog_rpt_team_recent_idx",
            ),
        ),
    ]
