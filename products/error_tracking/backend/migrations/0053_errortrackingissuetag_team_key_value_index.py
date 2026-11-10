from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0052_errortrackingissuetag"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingissuetag",
            index=models.Index(fields=["team", "key", "value"], include=["issue"], name="et_issue_tag_team_key_value"),
        ),
    ]
