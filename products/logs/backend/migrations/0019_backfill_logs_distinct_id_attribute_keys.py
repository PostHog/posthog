from django.db import migrations

BATCH_SIZE = 1000


def backfill_distinct_id_attribute_keys(apps, schema_editor):
    TeamLogsConfig = apps.get_model("logs", "TeamLogsConfig")
    # The ADD COLUMN default already filled every row with {posthogDistinctId}; only
    # rows with a customized single key need their value carried into the array.
    configs = TeamLogsConfig.objects.exclude(logs_distinct_id_attribute_key="posthogDistinctId")
    batch = []
    for config in configs.iterator(chunk_size=BATCH_SIZE):
        config.logs_distinct_id_attribute_keys = [config.logs_distinct_id_attribute_key]
        batch.append(config)
        if len(batch) >= BATCH_SIZE:
            TeamLogsConfig.objects.bulk_update(batch, ["logs_distinct_id_attribute_keys"])
            batch = []
    if batch:
        TeamLogsConfig.objects.bulk_update(batch, ["logs_distinct_id_attribute_keys"])


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0018_teamlogsconfig_logs_distinct_id_attribute_keys"),
    ]

    operations = [
        migrations.RunPython(backfill_distinct_id_attribute_keys, migrations.RunPython.noop),
    ]
