from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0201_warehousemigrationitem_claimed")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["schema", "team", "-created_at"],
                name="idx_extdatajob_schema_team",
            ),
        ),
    ]
