from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [("warehouse_sources", "0168_externaldataschema_scheduled_full_refresh")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="externaldatajob",
            index=models.Index(
                fields=["team", "finished_at"],
                condition=Q(billable=True, status="Completed"),
                name="idx_extdatajob_billable_fin",
            ),
        ),
    ]
