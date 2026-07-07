from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False

    dependencies = [
        ("signals", "0042_signalreport_status_before_suppression"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreporttask",
            index=models.Index(fields=["report", "relationship"], name="signals_report_task_rel_idx"),
        ),
    ]
