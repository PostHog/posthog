from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False

    dependencies = [("warehouse_sources", "0167_externaldatajob_running_idx")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["team", "finished_at"],
                condition=Q(billable=True, status="Completed"),
                include=["pipeline", "rows_synced", "destination_ids"],
                name="idx_extdatajob_team_billable",
            ),
        ),
    ]
