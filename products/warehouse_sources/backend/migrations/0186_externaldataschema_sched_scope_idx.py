from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0185_externaldatadestination_health")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldataschema",
            index=models.Index(
                condition=models.Q(
                    ("should_sync", True),
                    ("sync_frequency_interval__isnull", False),
                    models.Q(("deleted", True), _negated=True),
                ),
                fields=["id"],
                name="idx_extdataschema_sched_scope",
            ),
        ),
    ]
