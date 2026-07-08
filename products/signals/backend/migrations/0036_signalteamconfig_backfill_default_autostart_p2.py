from django.db import migrations


def bump_default_p0_to_p2(apps, schema_editor):
    """Raise teams still on the old P0 default up to the new P2 default.

    P0 was only ever the auto-created default (there's no UI to pick it), so a row at
    P0 reflects the old default rather than a deliberate choice. Rows set to any other
    priority are left untouched. SignalTeamConfig has one row per team, so a single
    filtered UPDATE is cheap.
    """
    SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")
    SignalTeamConfig.objects.filter(default_autostart_priority="P0").update(default_autostart_priority="P2")


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0035_signalteamconfig_default_autostart_priority_p2"),
    ]

    operations = [
        migrations.RunPython(bump_default_p0_to_p2, migrations.RunPython.noop),
    ]
