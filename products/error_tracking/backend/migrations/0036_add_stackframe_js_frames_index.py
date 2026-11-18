from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0035_alter_errortrackingstackframe_team"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingstackframe",
            index=models.Index(
                fields=["team", "created_at"],
                include=["resolved"],
                condition=models.Q(contents__lang="javascript"),
                name="et_frame_team_created_js_idx",
            ),
        ),
    ]
