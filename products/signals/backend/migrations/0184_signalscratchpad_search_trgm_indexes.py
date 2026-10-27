from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds can't run in a transaction.
    atomic = False

    dependencies = [("signals", "0183_spend_accounting_failures")]

    # The posthog app migrations already install pg_trgm.
    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscratchpad",
            index=GinIndex(OpClass(Upper("content"), name="gin_trgm_ops"), name="signal_scratchpad_content_trgm"),
        ),
        SafeAddIndexConcurrently(
            model_name="signalscratchpad",
            index=GinIndex(OpClass(Upper("key"), name="gin_trgm_ops"), name="signal_scratchpad_key_trgm"),
        ),
    ]
