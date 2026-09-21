from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0141_signalreport_recurrence_parent"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(fields=["recurrence_parent"], name="signals_recurrence_parent_idx"),
        ),
    ]
