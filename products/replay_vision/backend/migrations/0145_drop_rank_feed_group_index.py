from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0144_replay_cluster_review_and_group_names"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="replayobservation",
            name="rlo_ranked_feed_group_idx",
        ),
    ]
