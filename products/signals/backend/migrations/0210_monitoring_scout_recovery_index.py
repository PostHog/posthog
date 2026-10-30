from django.db import migrations, models
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import MD5

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0209_monitoring_agent_dispatch_backoff"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscoutrun",
            index=models.Index(
                models.F("team"),
                MD5(KeyTextTransform("run_note", "metadata")),
                condition=models.Q(metadata__triggered_by="monitoring"),
                name="signal_scout_monitor_note_idx",
            ),
        ),
    ]
