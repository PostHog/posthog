import django.db.models.deletion
import django.db.models.fields.json
import django.db.models.functions.comparison
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently, SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0130_rom_small_asset_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(
                    ("status", "succeeded"),
                    ("watch_rank__anchor_version", 1),
                    ("watch_rank__isnull", False),
                ),
                fields=["scanner", "created_at"],
                include=("id", "team", "completed_at"),
                name="rlo_ranked_count_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                models.F("scanner"),
                models.OrderBy(
                    django.db.models.functions.comparison.Cast(
                        django.db.models.fields.json.KeyTextTransform("contrast", "watch_rank"),
                        models.FloatField(),
                    ),
                    descending=True,
                ),
                models.OrderBy(models.F("id"), descending=True),
                condition=models.Q(
                    ("status", "succeeded"),
                    ("watch_rank__anchor_version", 1),
                    ("watch_rank__isnull", False),
                ),
                include=("team", "created_at", "completed_at", "watch_rank"),
                name="rlo_ranked_contrast_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                django.db.models.functions.comparison.Coalesce(
                    django.db.models.fields.json.KeyTextTransform("duplicate_of", "watch_rank"),
                    django.db.models.functions.comparison.Cast("id", models.CharField()),
                    output_field=models.CharField(),
                ),
                condition=models.Q(("status", "succeeded"), ("watch_rank__isnull", False)),
                name="rlo_ranked_group_idx",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="replayobservation",
            name="rlo_scanner_ranked_idx",
        ),
        SafeRemoveIndexConcurrently(
            model_name="replayobservation",
            name="rlo_workflow_id_idx",
        ),
        # Databases from before the replaylensobservation rename keep the old index names; fresh ones have Django's.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="replayobservation",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
                migrations.AlterField(
                    model_name="replayobservation",
                    name="scanner",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="observations",
                        to="replay_vision.replayscanner",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name=index_name,
                    table_name="replay_vision_replayobservation",
                    columns=columns,
                )
                for index_name, columns in (
                    ("replay_vision_replaylensobservation_team_id_b10decc8", '("team_id")'),
                    ("replay_vision_replayobservation_team_id_b204b330", '("team_id")'),
                    ("replay_vision_replaylensobservation_lens_id_4a4cd5c2", '("scanner_id")'),
                    ("replay_vision_replayobservation_scanner_id_f2400b26", '("scanner_id")'),
                )
            ],
        ),
    ]
