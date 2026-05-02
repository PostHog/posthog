from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("logs", "0007_backfill_check_interval_minutes"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="logsalertevent",
            index=models.Index(fields=["alert", "-created_at"], name="logs_alert_event_alert_ts_idx"),
        ),
    ]
