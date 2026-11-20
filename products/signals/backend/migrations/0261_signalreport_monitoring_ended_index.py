from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0260_signalreport_monitoring_ended_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                condition=models.Q(("monitoring_ended_at__isnull", False), ("status__in", ["resolved", "closed"])),
                fields=["team", "monitoring_ended_at"],
                name="signals_report_monitoring_end",
            ),
        ),
    ]
