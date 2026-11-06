from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("visual_review", "0017_toleratedhash_tolerated_repo_created"),
    ]

    # The covering index keeps the same key as the index it replaces, so every query that used the
    # old one can use the new one. It is built before the old one is dropped.
    operations = [
        SafeAddIndexConcurrently(
            model_name="runsnapshot",
            index=models.Index(
                fields=["run", "result"],
                include=[
                    "classification_reason",
                    "review_state",
                    "identifier",
                    "diff_percentage",
                    "tolerated_hash_match",
                    "team_id",
                ],
                name="snapshot_run_result_covering",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="runsnapshot",
            name="snapshot_run_result",
        ),
    ]
