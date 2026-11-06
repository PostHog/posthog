from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0165_scout_config_precheck"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscratchpad",
            index=models.Index(fields=["team", "-updated_at", "-id"], name="signal_scratchpad_team_upd_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="signalscratchpad",
            index=models.Index(
                fields=["team", "key"],
                name="signal_scratchpad_key_like_idx",
                opclasses=["int4_ops", "varchar_pattern_ops"],
            ),
        ),
    ]
