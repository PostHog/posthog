from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0227_monitoring_research_delivery")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportmonitoringattempt",
            index=models.Index(
                models.OrderBy(models.F("research_next_attempt_at"), nulls_first=True),
                models.F("research_requested_at"),
                models.F("id"),
                condition=models.Q(
                    ("research_requested_at__isnull", False),
                    models.Q(
                        ("research_delivery_status__isnull", True),
                        ("research_delivery_status__in", ["pending", "retryable"]),
                        _connector="OR",
                    ),
                ),
                name="signals_pending_research",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="signalemissionrecord",
            index=models.Index(
                fields=["team", "report_id", "emitted_at", "id"],
                condition=models.Q(source_product="signals_check", source_type="monitoring_unresolved"),
                name="signals_monitoring_report_idx",
            ),
        ),
    ]
