from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0217_monitoring_report_outcomes")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportmonitoringattempt",
            index=models.Index(
                models.F("tracker_issue_close_next_attempt_at").asc(nulls_first=True),
                models.F("tracker_issue_close_requested_at"),
                models.F("id"),
                condition=models.Q(
                    tracker_issue_close_requested_at__isnull=False, tracker_issue_close_processed_at__isnull=True
                ),
                name="signals_pending_tracker_close",
            ),
        ),
    ]
