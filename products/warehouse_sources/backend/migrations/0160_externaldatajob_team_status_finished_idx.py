from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0159_externaldatajob_destination_ids_and_more")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["team", "status", "finished_at"],
                name="idx_extdatajob_team_stat_fin",
                condition=models.Q(billable=True),
            ),
        ),
    ]
