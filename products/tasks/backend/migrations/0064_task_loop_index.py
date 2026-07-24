from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # posthog_task is large enough that a plain CREATE INDEX would hold an ACCESS EXCLUSIVE
    # lock for the whole build. CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0063_loop_looptrigger_loopfire"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["loop"], name="posthog_task_loop_idx"),
        ),
    ]
