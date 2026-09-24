from django.db import migrations


def enable_pull_request_label(apps, schema_editor):
    """Turn the label on for every team that still holds the old default.

    The switch shipped opt-in about a day before this migration, so a `false` today means the team
    never opened the settings page rather than that it declined. A `false` written after this runs
    is a real refusal, and no later migration touches it.
    """
    SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")
    SignalTeamConfig.objects.filter(pull_request_label_enabled=False).update(pull_request_label_enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0155_alter_signalteamconfig_pull_request_label_enabled"),
    ]

    # Reverse is a noop: turning every row back off would also clear the teams that asked for the
    # label before this ran.
    operations = [
        migrations.RunPython(enable_pull_request_label, migrations.RunPython.noop, elidable=True),
    ]
