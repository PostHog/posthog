from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building and dropping the indexes does not take an ACCESS EXCLUSIVE
    # lock on posthog_task. Concurrent index work cannot run in a transaction, so the
    # migration is non-atomic.
    atomic = False

    dependencies = [
        ("tasks", "0117_task_set_null_cascade_indexes"),
    ]

    operations = [
        # Added before the narrower index it replaces is dropped, so the task list keeps an
        # index for its sort at all times.
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["team", "internal", "archived", "-created_at", "-id"],
                include=["channel", "created_by", "origin_product"],
                condition=models.Q(deleted=False),
                name="posthog_task_live_crt_cov_idx",
            ),
        ),
        SafeRemoveIndexConcurrently(model_name="task", name="posthog_task_team_live_crt_idx"),
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["team", "internal", "repository"],
                include=["channel", "created_by", "origin_product"],
                condition=models.Q(deleted=False, repositories=[]),
                name="posthog_task_repo_legacy_idx",
            ),
        ),
    ]
