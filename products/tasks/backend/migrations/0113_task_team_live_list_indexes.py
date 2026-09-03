from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building and dropping the indexes does not take an ACCESS EXCLUSIVE
    # lock on posthog_task. Concurrent index work cannot run in a transaction, so the
    # migration is non-atomic.
    atomic = False

    dependencies = [
        ("tasks", "0112_taskrun_terminal_updated_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["team", "internal", "archived", "-created_at", "-id"],
                condition=models.Q(deleted=False),
                name="posthog_task_team_live_crt_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["team", "internal", "archived", "-last_activity_at", "-id"],
                condition=models.Q(deleted=False),
                name="posthog_task_team_live_act_idx",
            ),
        ),
        # Keep the broad ordering indexes for callers that intentionally leave
        # `internal` or `archived` unconstrained.
        SafeRemoveIndexConcurrently(model_name="task", name="posthog_task_archived_idx"),
    ]
