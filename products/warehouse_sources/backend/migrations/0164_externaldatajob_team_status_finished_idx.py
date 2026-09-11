from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0163_externaldataschema_auto_disabled_at")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["team", "status", "billable", "finished_at"],
                name="idx_extdatajob_team_stat_fin",
            ),
        ),
    ]
