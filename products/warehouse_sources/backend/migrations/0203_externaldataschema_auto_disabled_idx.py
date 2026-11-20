from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0202_externaldatajob_schema_team_created_idx")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldataschema",
            index=models.Index(
                fields=["-auto_disabled_at"],
                name="idx_extschema_auto_disabled",
                condition=models.Q(auto_disabled_at__isnull=False),
            ),
        ),
    ]
