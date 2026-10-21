from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("workflows", "0037_hogflow_team_source_record_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="hogflowbatchjob",
            index=models.Index(
                "team",
                "hog_flow",
                models.F("updated_at").desc(),
                condition=models.Q(status="completed"),
                name="hogflowbatchjob_latest_send",
            ),
        ),
    ]
