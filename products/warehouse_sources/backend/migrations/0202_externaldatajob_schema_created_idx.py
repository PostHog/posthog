from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("warehouse_sources", "0201_warehousemigrationitem_claimed"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["schema", "-created_at"],
                name="idx_extdatajob_schema_created",
            ),
        ),
    ]
