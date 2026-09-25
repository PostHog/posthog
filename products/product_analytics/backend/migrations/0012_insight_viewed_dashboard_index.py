from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("product_analytics", "0011_insight_viewed_context_fields")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="insightviewed",
            index=models.Index(
                fields=["dashboard"], condition=models.Q(dashboard__isnull=False), name="insightviewed_dashboard_idx"
            ),
        ),
    ]
