from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds can't run in a transaction.
    atomic = False

    dependencies = [("signals", "0173_signalreportslackthread_kind_target_reply_ts")]

    # pg_trgm is already installed (posthog migration 0034).
    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="signals_report_title_trgm"),
        ),
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=GinIndex(OpClass(Upper("summary"), name="gin_trgm_ops"), name="signals_report_summary_trgm"),
        ),
    ]
