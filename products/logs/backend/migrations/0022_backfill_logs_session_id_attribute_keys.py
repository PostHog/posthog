from django.db import migrations

BATCH_SIZE = 1000

# No SDK emits this key, so a team still carrying it as its stored default resolves nothing
# wherever detection trusts the configured keys.
OLD_DEFAULT = ["posthogSessionId"]

# The old key stays first. Some pipelines do emit it, and detection is first-match-wins, so
# reordering these two would move those teams onto a different attribute.
NEW_VALUE = ["posthogSessionId", "sessionId"]


def backfill_session_id_attribute_keys(apps, schema_editor):
    TeamLogsConfig = apps.get_model("logs", "TeamLogsConfig")
    configs = TeamLogsConfig.objects.filter(logs_session_id_attribute_keys=OLD_DEFAULT)
    batch = []
    for config in configs.iterator(chunk_size=BATCH_SIZE):
        config.logs_session_id_attribute_keys = list(NEW_VALUE)
        batch.append(config)
        if len(batch) >= BATCH_SIZE:
            TeamLogsConfig.objects.bulk_update(batch, ["logs_session_id_attribute_keys"])
            batch = []
    if batch:
        TeamLogsConfig.objects.bulk_update(batch, ["logs_session_id_attribute_keys"])


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0021_logsalertconfiguration_schedule_restriction"),
    ]

    operations = [
        migrations.RunPython(backfill_session_id_attribute_keys, migrations.RunPython.noop),
    ]
