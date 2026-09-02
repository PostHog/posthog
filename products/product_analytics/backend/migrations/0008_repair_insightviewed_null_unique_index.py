from django.db import migrations
from django.db.models import Max, Subquery

import structlog

from posthog.migration_helpers import CreateIndexConcurrently

logger = structlog.get_logger(__name__)


def clean_duplicates(apps, schema_editor):
    InsightViewed = apps.get_model("product_analytics", "InsightViewed")

    null_rows = InsightViewed.objects.filter(team__isnull=True, user__isnull=True)
    # Keep the newest row, the highest id, for each insight.
    keep_ids = null_rows.values("insight_id").annotate(keep_id=Max("id")).values("keep_id")
    deleted_count, _ = null_rows.exclude(id__in=Subquery(keep_ids)).delete()

    logger.info("clean_duplicates_complete", deleted_count=deleted_count)


class Migration(migrations.Migration):
    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("product_analytics", "0007_fix_insightviewed_null_duplicates"),
    ]

    operations = [
        # A duplicate can reappear between 0007's cleanup and this build: anonymous
        # shared-insight views write null-team/null-user rows through a racy
        # update_or_create. That duplicate fails the unique build, and this migration
        # is recorded applied only on success, so every bin/migrate retry runs it
        # alone. Re-run the cleanup as the first operation so each retry deletes the
        # new duplicate before rebuilding, and the repair self-heals instead of
        # staying blocked. The cleanup and the build must share one migration; a
        # separate cleanup would commit on its own and leave the retry rebuilding
        # against the same duplicate.
        migrations.RunPython(clean_duplicates, migrations.RunPython.noop, elidable=True),
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
