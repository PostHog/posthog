import django.db.models.fields.json
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0152_replay_scanner_scope"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayscanner",
            index=models.Index(
                django.db.models.fields.json.KeyTransform("experiment_id", "scope"),
                name="rl_scope_experiment_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="replayobservation",
            index=models.Index(
                condition=models.Q(("group_key__isnull", False)),
                fields=["scanner", "group_key"],
                name="rlo_scanner_group_idx",
            ),
        ),
    ]
