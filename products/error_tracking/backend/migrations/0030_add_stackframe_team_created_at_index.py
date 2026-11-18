from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0029_remove_symbolset_used_created_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingstackframe",
            index=models.Index(fields=["team", "created_at"], name="et_frame_team_created_at_idx"),
        ),
    ]
