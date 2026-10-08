from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0127_add_twd_pending_due_order_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskworkflowdispatch",
            index=models.Index(
                fields=["lease_expires_at", "next_attempt_at", "created_at"],
                name="twd_claimed_lease_order",
                condition=models.Q(status="claimed"),
            ),
        ),
    ]
