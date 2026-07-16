from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("error_tracking", "0020_errortrackingsettings_autocapture_exceptions_opt_in"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingstackframe",
            index=models.Index(fields=["team_id", "created_at"], name="et_frame_team_created_idx"),
        ),
    ]
