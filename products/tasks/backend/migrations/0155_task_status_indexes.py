import django.contrib.postgres.indexes
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0154_task_status"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["status"],
                condition=models.Q(("status__in", ["queued", "running"])),
                name="posthog_task_live_status_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["head_branch"],
                condition=models.Q(("head_branch__isnull", False)),
                name="posthog_task_head_branch_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="task",
            index=django.contrib.postgres.indexes.GinIndex(fields=["pr_urls"], name="posthog_task_pr_urls_idx"),
        ),
    ]
