from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("web_analytics", "0015_heatmap_page_history")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="savedheatmap",
            index=models.Index(fields=["last_viewed_at"], name="heatmap_last_viewed_idx"),
        ),
    ]
