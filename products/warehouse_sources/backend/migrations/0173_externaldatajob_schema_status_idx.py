from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0172_migrate_apple_search_ads_job_inputs_to_auth_method")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["team", "pipeline", "schema", "status", "created_at"],
                name="idx_extdatajob_schema_status",
            ),
        ),
    ]
