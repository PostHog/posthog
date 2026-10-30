import django.db.models.fields.json
import django.db.models.functions.comparison
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0133_scanner_semantics"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                django.db.models.functions.comparison.Coalesce(
                    django.db.models.fields.json.KeyTextTransform("group", "watch_rank"),
                    django.db.models.functions.comparison.Cast("id", models.CharField()),
                    output_field=models.CharField(),
                ),
                condition=models.Q(("status", "succeeded"), ("watch_rank__isnull", False)),
                name="rlo_ranked_feed_group_idx",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="replayobservation",
            name="rlo_ranked_group_idx",
        ),
    ]
