import django.db.models.fields.json
import django.db.models.functions.comparison
from django.db import migrations, models

from posthog.migration_helpers import (
    DropFieldIndexesConcurrently,
    SafeAddIndexConcurrently,
    SafeRemoveIndexConcurrently,
)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0131_rename_legacy_field_indexes"),
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
        DropFieldIndexesConcurrently(model_name="replayobservation", name="team"),
        DropFieldIndexesConcurrently(model_name="replayobservation", name="scanner"),
    ]
