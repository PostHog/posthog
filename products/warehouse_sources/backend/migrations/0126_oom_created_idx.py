from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False
    dependencies = [("warehouse_sources", "0125_oom_event_workload_evidence")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldataschemaoomevent",
            index=models.Index(fields=["created_at", "schema", "team"], name="dwh_oom_created_idx"),
        ),
    ]
