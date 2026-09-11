from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0036_add_stackframe_js_frames_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["team", "created_at", "id"], name="et_symset_team_created_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["team", "last_used", "id"], name="et_symset_team_used_idx"),
        ),
    ]
