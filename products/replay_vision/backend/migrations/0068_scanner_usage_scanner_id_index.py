from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block. Isolated from the schema
    # changes in 0066 so those keep atomic rollback safety while the index build stays non-blocking.
    atomic = False

    dependencies = [
        ("replay_vision", "0067_scanner_credit_limit"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="replayobservationusage",
            index=models.Index(
                condition=models.Q(("scanner_id__isnull", False)),
                fields=["scanner_id", "observation_created_at"],
                name="rlou_scanner_created_idx",
            ),
        ),
    ]
