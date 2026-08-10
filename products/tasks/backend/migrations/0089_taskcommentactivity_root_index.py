from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0088_backfill_pr_created_event_key"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskcommentactivity",
            index=models.Index(fields=["team", "root_comment", "kind"], name="task_comment_activity_root"),
        ),
    ]
