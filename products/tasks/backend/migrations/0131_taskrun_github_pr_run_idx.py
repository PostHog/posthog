from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0130_remove_twd_claimed_lease_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["created_at"],
                name="task_run_github_pr_run_idx",
                condition=models.Q(output__pr_url__startswith="https://github.com/"),
            ),
        ),
    ]
