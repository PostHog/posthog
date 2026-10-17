from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds can't run in a transaction.
    atomic = False

    dependencies = [("signals", "0185_signalscoutconfig_last_precheck")]

    # The posthog app migrations already install pg_trgm.
    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscoutrun",
            index=GinIndex(OpClass(Upper("summary"), name="gin_trgm_ops"), name="signal_scout_run_summary_trgm"),
        ),
    ]
