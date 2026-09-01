from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False
    dependencies = [("warehouse_sources", "0157_reset_plausible_page_breakdowns")]

    operations = [
        # `posthog_externaldatasource` carried only the primary key and the automatic `team_id`
        # btree. Scheduled sweeps that filter by `source_type` (and `prefix`) with no team predicate
        # scanned every row. A plain (non-partial) index covers those filters. It is not keyed on
        # `deleted` on purpose: `deleted` is nullable, so a `deleted = false` partial predicate would
        # miss the NULL rows that `exclude(deleted=True)` still returns.
        SafeAddIndexConcurrently(
            model_name="externaldatasource",
            index=models.Index(
                fields=["source_type", "prefix"],
                name="idx_extdatasource_type_prefix",
            ),
        ),
    ]
