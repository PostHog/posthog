from django.db import migrations


def reset_everyone_to_p4_default(apps, schema_editor):
    """Land everyone on the new P4 auto-start default.

    The per-user / per-team threshold UI is being removed, so there's no longer a
    way to pick a value — everyone runs on the team default, which is now P4.

    1. Move every team config up to P4. The threshold was previously editable, so
       a row may hold any value (P0–P4); a single unfiltered UPDATE is cheap since
       SignalTeamConfig has one row per team.
    2. Clear any per-user override (set ``autostart_priority`` to NULL) so it falls
       back to the team default of P4. We leave the rest of the row intact, so Slack
       notification settings on the same model are preserved. Users who explicitly
       opted out delete their whole config row, so they have no row here and stay
       opted out — this only touches rows that already exist.
    """
    SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")
    SignalTeamConfig.objects.exclude(default_autostart_priority="P4").update(default_autostart_priority="P4")

    SignalUserAutonomyConfig = apps.get_model("signals", "SignalUserAutonomyConfig")
    SignalUserAutonomyConfig.objects.exclude(autostart_priority__isnull=True).update(autostart_priority=None)


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0045_signalteamconfig_default_autostart_priority_p4"),
    ]

    operations = [
        migrations.RunPython(reset_everyone_to_p4_default, migrations.RunPython.noop),
    ]
