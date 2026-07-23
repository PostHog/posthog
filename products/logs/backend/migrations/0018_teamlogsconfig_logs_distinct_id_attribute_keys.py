import django.contrib.postgres.fields
from django.db import migrations, models

import products.logs.backend.models


def backfill_distinct_id_attribute_keys(apps, schema_editor):
    TeamLogsConfig = apps.get_model("logs", "TeamLogsConfig")
    # The ADD COLUMN default already filled every row with {posthogDistinctId}; only
    # rows with a customized single key need their value carried into the array.
    configs = TeamLogsConfig.objects.exclude(logs_distinct_id_attribute_key="posthogDistinctId")
    for config in configs.iterator():
        config.logs_distinct_id_attribute_keys = [config.logs_distinct_id_attribute_key]
        config.save(update_fields=["logs_distinct_id_attribute_keys"])


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0017_logsmetricrule"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamlogsconfig",
            name="logs_distinct_id_attribute_keys",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=200),
                db_default=models.Value("{posthogDistinctId}"),
                default=products.logs.backend.models.default_logs_distinct_id_attribute_keys,
                size=None,
            ),
        ),
        migrations.RunPython(backfill_distinct_id_attribute_keys, migrations.RunPython.noop),
    ]
