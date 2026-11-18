from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0166_signalscratchpad_indexes")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscoutrun",
            index=models.Index(fields=["team", "-created_at"], name="signal_scout_run_team_new_idx"),
        ),
    ]
