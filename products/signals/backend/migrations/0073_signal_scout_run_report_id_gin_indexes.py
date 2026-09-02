from django.contrib.postgres.indexes import GinIndex
from django.db import migrations

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0072_signalscoutnote_origin"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscoutrun",
            index=GinIndex(fields=["emitted_report_ids"], name="signal_scout_run_emitted_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="signalscoutrun",
            index=GinIndex(fields=["edited_report_ids"], name="signal_scout_run_edited_idx"),
        ),
    ]
