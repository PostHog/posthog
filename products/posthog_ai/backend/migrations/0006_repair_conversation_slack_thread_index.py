from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("posthog_ai", "0005_check_duplicate_slack_thread_keys"),
    ]

    operations = [
        # Migration ee.0035 built this index with a raw `CREATE UNIQUE INDEX CONCURRENTLY
        # IF NOT EXISTS`. Postgres matches `IF NOT EXISTS` by name and not by validity, so
        # where a build was cancelled the invalid index stayed and every retry skipped it.
        # `CreateIndexConcurrently` drops the invalid leftover before it rebuilds.
        # Model state already carries the constraint, so this migration adds no state operation.
        CreateIndexConcurrently(
            index_name="unique_team_slack_thread_key",
            table_name="ee_conversation",
            columns="(team_id, slack_thread_key)",
            unique=True,
            where='WHERE "slack_thread_key" IS NOT NULL',
        ),
    ]
