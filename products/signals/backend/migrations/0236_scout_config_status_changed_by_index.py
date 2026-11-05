from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0235_signalspend_usage_billing")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscoutconfig",
            index=models.Index(
                fields=["status_changed_by"],
                condition=models.Q(status_changed_by__isnull=False),
                name="scout_config_status_by_idx",
            ),
        ),
    ]
