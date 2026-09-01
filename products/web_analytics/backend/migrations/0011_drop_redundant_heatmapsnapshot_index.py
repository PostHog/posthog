from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("web_analytics", "0010_contentautopilotrun_content_auto_run_active"),
    ]

    operations = [
        # Redundant with the unique_together=("heatmap", "width") btree, so the planner never uses it.
        SafeRemoveIndexConcurrently(
            model_name="heatmapsnapshot",
            name="posthog_hea_heatmap_9543e8_idx",
        ),
    ]
