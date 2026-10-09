from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0135_usertasksconfig_task_defaults"),
    ]

    operations = [
        # The column and its index stay until a later drop, so pods on the old release keep working.
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveIndex(model_name="task", name="posthog_task_loop_idx")],
        ),
        untrack_field("task", "loop", database_operations=[DropForeignKey("posthog_task", column="loop_id")]),
    ]
