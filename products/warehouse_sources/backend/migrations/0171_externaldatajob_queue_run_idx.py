from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("warehouse_sources", "0170_externaldatajob_phase"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["team", "workflow_run_id", "-created_at"],
                condition=models.Q(workflow_run_id__isnull=False),
                name="idx_extjob_team_wfrun_created",
            ),
        ),
    ]
