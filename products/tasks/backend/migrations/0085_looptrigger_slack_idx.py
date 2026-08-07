from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False

    dependencies = [
        ("tasks", "0084_looptrigger_slack_fields"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="looptrigger",
            index=models.Index(fields=["slack_integration_id"], name="task_loop_trigger_slack_idx"),
        ),
    ]
