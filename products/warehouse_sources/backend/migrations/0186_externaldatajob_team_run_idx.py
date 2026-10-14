from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0185_externaldatadestination_health")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                condition=models.Q(workflow_run_id__isnull=False),
                fields=["team", "workflow_run_id"],
                name="idx_extdatajob_team_run",
            ),
        ),
    ]
