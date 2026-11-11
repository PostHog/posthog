from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0240_one_time_trial")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalspend",
            index=models.Index(fields=["trial_grant"], name="signals_spend_trial_grant_idx"),
        ),
    ]
