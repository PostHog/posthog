from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0221_signal_filter_catalog")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(fields=["team", "-updated_at", "id"], name="signals_report_team_updated"),
        ),
    ]
