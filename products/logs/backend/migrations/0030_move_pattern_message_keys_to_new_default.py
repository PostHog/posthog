from django.db import migrations

OLD_DEFAULT = ["message", "msg", "event"]
NEW_DEFAULT = ["message", "msg", "log", "msg_", "_msg", "content", "event", "fields.message", "error", "fields.error"]


# A config row stores its keys, so a row created with the old default keeps the old list after the
# default changes. Query-time pattern mining now reads this list, so a row left on the old list would
# stop splitting Rust `tracing` key-set groups by `fields.message`. A row that a person saved with
# exactly the old list cannot be told apart, so it moves too. Rows with any other list stay unchanged.
# The UPDATE takes row locks only, and those block nothing but a concurrent save of the same team's
# logs settings, so one statement in the migration transaction is enough.
def _replace_keys(apps, old: list[str], new: list[str]) -> None:
    TeamLogsConfig = apps.get_model("logs", "TeamLogsConfig")
    TeamLogsConfig.objects.filter(logs_pattern_message_keys=old).update(logs_pattern_message_keys=new)


def forwards(apps, schema_editor):
    _replace_keys(apps, OLD_DEFAULT, NEW_DEFAULT)


def backwards(apps, schema_editor):
    _replace_keys(apps, NEW_DEFAULT, OLD_DEFAULT)


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0029_pattern_message_key_paths"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
