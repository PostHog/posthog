from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0111_signalreport_metrics"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                models.OrderBy(models.F("metrics_last_refresh_attempt_at"), nulls_first=True),
                models.F("id"),
                condition=(
                    models.Q(status__in=["ready", "pending_input"])
                    & models.Q(metrics__contains=[{"kind": "affected_users"}])
                ),
                name="signals_report_metric_refresh",
            ),
        ),
    ]
