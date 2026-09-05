from django.db import migrations
from django.db.models import Max, Subquery

import structlog

logger = structlog.get_logger(__name__)


def clean_duplicates(apps, schema_editor):
    InsightViewed = apps.get_model("product_analytics", "InsightViewed")

    null_rows = InsightViewed.objects.filter(team__isnull=True, user__isnull=True)
    # Keep the newest row, the highest id, for each insight.
    keep_ids = null_rows.values("insight_id").annotate(keep_id=Max("id")).values("keep_id")
    deleted_count, _ = null_rows.exclude(id__in=Subquery(keep_ids)).delete()

    logger.info("clean_duplicates_complete", deleted_count=deleted_count)


class Migration(migrations.Migration):
    dependencies = [
        ("product_analytics", "0006_insightvariable_values_query_connection_id"),
    ]

    operations = [
        # Migration 0946 cleaned these rows once, but the partial unique index that
        # migration 0947 was meant to add never became valid in every region, so
        # duplicates can have built up again.
        migrations.RunPython(clean_duplicates, migrations.RunPython.noop, elidable=True),
    ]
