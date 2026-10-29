from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0142_replay_cluster_membership"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("feed_group_id__isnull", False), ("status", "succeeded")),
                fields=["feed_group_id", "created_at"],
                name="rlo_feed_group_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("search_theme_id__isnull", False), ("status", "succeeded")),
                fields=["search_theme_id", "created_at"],
                name="rlo_search_theme_idx",
            ),
        ),
    ]
