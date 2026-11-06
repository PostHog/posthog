from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # `SafeAddIndexConcurrently` cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("signals", "0101_signalscoutconfig_source_id_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalscoutconfig",
            index=models.Index(
                fields=["team", "source_product", "source_id"],
                name="scout_config_source_idx",
            ),
        ),
    ]
