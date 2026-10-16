from django.db import migrations, models
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0189_trial_reconciliation_queue")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signaltrialoperation",
            index=models.Index(
                Coalesce("next_reconcile_at", "admitted_at"),
                "admitted_at",
                condition=models.Q(funding="trial"),
                name="signals_trial_reconcile_due",
            ),
        ),
    ]
