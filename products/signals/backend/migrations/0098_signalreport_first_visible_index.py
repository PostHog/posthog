from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for concurrent index creation

    dependencies = [("signals", "0097_signalreport_first_visible_at_and_more")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                condition=models.Q(("first_visible_at__isnull", False)),
                fields=["team", "first_visible_at"],
                name="signals_report_first_visible",
            ),
        ),
    ]
