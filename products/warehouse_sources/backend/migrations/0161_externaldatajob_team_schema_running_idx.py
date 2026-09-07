from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0160_datawarehousetable_dwtable_team_live_created")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                condition=models.Q(("status", "Running")),
                fields=["team", "schema"],
                name="idx_extdatajob_team_schema_run",
            ),
        ),
    ]
