from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0235_signalspend_usage_billing"),
    ]

    operations = [
        untrack_field("signalteamconfig", "anomaly_scoring_enabled"),
    ]
