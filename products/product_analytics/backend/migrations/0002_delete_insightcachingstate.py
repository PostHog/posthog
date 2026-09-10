# State-only removal of InsightCachingState. The posthog_insightcachingstate table is
# intentionally kept so code still running during the rolling deploy can write to it;
# it gets dropped in a follow-up migration after a full deploy cycle
# (see safe-django-migrations.md, "Dropping Tables").

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("product_analytics", "0001_migrate_product_analytics_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="InsightCachingState",
                ),
            ],
            database_operations=[],
        ),
    ]
