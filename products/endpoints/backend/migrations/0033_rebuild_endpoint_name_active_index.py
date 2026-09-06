from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("endpoints", "0032_check_duplicate_active_endpoint_names"),
    ]

    # 0016 created this index with a bare `IF NOT EXISTS`, which skips an existing index without
    # checking `indisvalid`, so a cancelled build can leave it enforcing nothing.
    # `CreateIndexConcurrently` drops an invalid leftover first. Django state came from 0016.
    operations = [
        CreateIndexConcurrently(
            index_name="team_id_endpoint_name_active",
            table_name="endpoints_endpoint",
            columns='("team_id", "name")',
            unique=True,
            where='WHERE (NOT "deleted" OR "deleted" IS NULL)',
        ),
    ]
