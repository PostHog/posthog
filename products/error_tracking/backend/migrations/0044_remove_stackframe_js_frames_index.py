from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0043_errortrackingissue_active_created_idx"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="errortrackingstackframe",
            name="et_frame_team_created_js_idx",
        ),
    ]
