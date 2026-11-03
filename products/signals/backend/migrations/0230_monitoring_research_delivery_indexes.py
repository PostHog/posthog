from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0229_monitoring_research_delivery")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportmonitoringattempt",
            index=models.Index(
                models.OrderBy(models.F("research_next_attempt_at"), nulls_first=True),
                models.F("research_requested_at"),
                models.F("id"),
                condition=models.Q(research_requested_at__isnull=False, research_processed_at__isnull=True),
                name="signals_pending_research",
            ),
        ),
    ]
