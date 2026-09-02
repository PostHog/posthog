from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("error_tracking", "0031_errortrackingalert_errortrackingalertdestination_and_more"),
    ]

    operations = [
        # `posthog_err_team_id_dc6a7f_idx` is a (team_id, raw_id) btree that posthog migration
        # 0500 created. Migration 0006 removed it from Django state but its `database_operations`
        # never dropped it, so the btree can still exist while Django believes it is gone. This
        # migration carries no state operation for that reason.
        #
        # The `unique_team_id_raw_id_part` constraint leads with the same (team_id, raw_id)
        # columns, so it serves every scan this index served. What the index still costs is write
        # amplification on every insert, delete, and symbol set cleanup update against a very
        # large and continuously churned table.
        DropIndexConcurrently(
            index_name="posthog_err_team_id_dc6a7f_idx",
            table_name="posthog_errortrackingstackframe",
            columns="(team_id, raw_id)",
        ),
    ]
