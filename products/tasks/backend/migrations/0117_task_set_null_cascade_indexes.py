from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # posthog_task is large enough that a plain CREATE INDEX would hold an ACCESS EXCLUSIVE
    # lock for the whole build. CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0116_drop_task_session_storage_key_like_index"),
    ]

    operations = [
        # Both columns are only filtered on their own by the SET_NULL cascade Django emits
        # when a User or a UserIntegration row is deleted.
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["created_by"], name="posthog_task_creator_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["github_user_integration"], name="posthog_task_gh_user_int_idx"),
        ),
    ]
