from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("logs", "0027_logsalertevent_handback_kind"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="logsalertevent",
            index=models.Index(fields=["alert", "kind", "-created_at"], name="logs_alert_event_kind_ts_idx"),
        ),
    ]
