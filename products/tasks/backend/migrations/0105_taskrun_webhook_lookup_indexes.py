from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations, models
from django.db.models.fields.json import KeyTransform

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1315_githubinstallrequest_account"),
        ("tasks", "0104_desktop_beta_terms_acceptance"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=GinIndex(
                OpClass(KeyTransform("verified_pr_urls", "state"), name="jsonb_path_ops"),
                name="task_run_verified_pr_urls_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=GinIndex(
                OpClass(KeyTransform("head_branches", "output"), name="jsonb_path_ops"),
                name="task_run_head_branches_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["branch"],
                name="task_run_branch_idx",
                condition=models.Q(branch__isnull=False),
            ),
        ),
    ]
