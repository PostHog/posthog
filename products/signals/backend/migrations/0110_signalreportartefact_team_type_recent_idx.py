from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0109_signal_scout_suggestion_set"),
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
