import django.db.models.fields.json
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0053_sandboxcustomimage_build_log"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                django.db.models.fields.json.KeyTransform("wizard_head_branch", "state"),
                name="task_run_wizard_branch_idx",
                condition=models.Q(state__wizard_head_branch__isnull=False),
            ),
        ),
    ]
