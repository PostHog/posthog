from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0108_signalscratchpad_created_by_identity"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(
                fields=["team", "type", "-created_at"],
                name="signals_sig_team_type_ct_idx",
            ),
        ),
    ]
