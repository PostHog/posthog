from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0129_remove_twd_pending_due_idx"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="taskworkflowdispatch",
            name="twd_claimed_lease",
        ),
    ]
