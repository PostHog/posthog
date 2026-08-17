from django.db import migrations

BATCH_SIZE = 1000

# Teams that existed when 0015 added the column carry its ADD COLUMN default,
# `{posthogSessionId}`. Our SDKs emit `sessionId`, which is also what
# https://posthog.com/docs/logs/link-session-replay tells backends to send, so those teams'
# session links resolve nothing wherever detection trusts the configured keys. Some customer
# pipelines do emit `posthogSessionId` directly — hence the append below rather than a swap.
OLD_DEFAULT = ["posthogSessionId"]

# Appended rather than prepended, and rather than replaced. Detection is first-match-wins,
# and a stored `["posthogSessionId"]` is indistinguishable from a team that configured it
# deliberately — 31 teams do emit that key, 14 of them alongside `sessionId` (measured in
# ClickHouse, 2026-08-17). Putting `sessionId` first would switch those 14 onto a different
# attribute than the one they resolve on today. Keeping the old key first leaves every
# team that emits it resolving exactly as before, while the ~2,150 teams that emit only
# `sessionId` start resolving at all.
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
