from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently

_REAPABLE = ("candidate", "in_progress", "pending_input", "ready")


class Migration(migrations.Migration):
    atomic = False  # Required for concurrent index creation

    dependencies = [("signals", "0117_signalreport_last_activity_at_and_more")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                condition=models.Q(("status__in", _REAPABLE)),
                fields=["last_activity_at"],
                name="signals_report_last_activity",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                condition=models.Q(("status__in", _REAPABLE)),
                fields=["last_human_touch_at"],
                name="signals_report_human_touch",
            ),
        ),
    ]
