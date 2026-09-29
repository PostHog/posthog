from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0128_add_twd_claimed_lease_order_idx"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="taskworkflowdispatch",
            name="twd_pending_due",
        ),
    ]
