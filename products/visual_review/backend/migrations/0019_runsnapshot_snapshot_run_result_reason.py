import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently, SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("visual_review", "0018_runsnapshot_snapshot_run_result_covering"),
    ]

    # The new index starts with the same (run, result) key as the one it replaces, so every query
    # that used the old one can use the new one. It is built before the old one is dropped.
    operations = [
        SafeAddIndexConcurrently(
            model_name="runsnapshot",
            index=models.Index(
                fields=["run", "result", "classification_reason"],
                include=["review_state", "identifier", "diff_percentage", "tolerated_hash_match", "team_id"],
                name="snapshot_run_result_reason",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="runsnapshot",
            name="snapshot_run_result_covering",
        ),
        # The foreign key's own index duplicates the leading column of the indexes above and of
        # the unique (run, identifier) constraint.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="runsnapshot",
                    name="run",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="snapshots",
                        to="visual_review.run",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="visual_review_runsnapshot_run_id_e4e3613d",
                    table_name="visual_review_runsnapshot",
                    columns="(run_id)",
                ),
            ],
        ),
    ]
