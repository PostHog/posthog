from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0184_signalreport_ready_event_emitted_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                condition=models.Q(
                    ("ready_event_delivered_at__isnull", True), ("ready_event_emitted_at__isnull", False)
                ),
                fields=["ready_event_emitted_at"],
                name="signals_report_ready_unsent",
            ),
        ),
    ]
