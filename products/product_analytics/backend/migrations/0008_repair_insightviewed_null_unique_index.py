from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("product_analytics", "0007_fix_insightviewed_null_duplicates"),
    ]

    operations = [
        # Migration 0947 built this index with a raw `CREATE UNIQUE INDEX CONCURRENTLY
        # IF NOT EXISTS`. Postgres matches `IF NOT EXISTS` by name and not by validity, so
        # where a build was cancelled the invalid index stayed and every retry skipped it.
        # `CreateIndexConcurrently` drops the invalid leftover before it rebuilds.
        # The index is not part of model state, so this migration adds no state operation.
        CreateIndexConcurrently(
            index_name="posthog_insightviewed_null_team_user_unique",
            table_name="posthog_insightviewed",
            columns="(insight_id)",
            unique=True,
            where='WHERE "team_id" IS NULL AND "user_id" IS NULL',
        ),
    ]
