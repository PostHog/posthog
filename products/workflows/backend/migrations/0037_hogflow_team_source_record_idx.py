from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("workflows", "0036_hogflow_source_record"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="hogflow",
            index=models.Index(
                condition=models.Q(source_record__isnull=False),
                fields=["team", "source_record"],
                name="hogflow_team_source_record_idx",
            ),
        ),
    ]
