from django.db import migrations


def reset_everyone_to_p3_default(apps, schema_editor):
    """Land everyone on the new P3 auto-start default so P4 reports no longer auto-start.

    The threshold is not user-configurable in the inbox UI, so everyone runs on the team
    default. That default is now P3, meaning only P0-P3 reports auto-open a PR and P4 (all
    priorities / lowest) reports stop auto-starting.

    1. Move every team config to P3. There is one row per team, so a single unfiltered UPDATE
       is cheap. After the previous P4 backfill every row sits at P4; this brings them to P3.
    2. Clear any per-user override (set ``autostart_priority`` to NULL) so it falls back to the
       team default of P3. The rest of the row is left intact, so Slack notification settings on
       the same model are preserved. Users who explicitly opted out delete their whole config
       row, so they have no row here and stay opted out — this only touches rows that exist.
    """
    SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")
    SignalTeamConfig.objects.exclude(default_autostart_priority="P3").update(default_autostart_priority="P3")

    SignalUserAutonomyConfig = apps.get_model("signals", "SignalUserAutonomyConfig")
    SignalUserAutonomyConfig.objects.exclude(autostart_priority__isnull=True).update(autostart_priority=None)


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0055_signalteamconfig_default_autostart_priority_p3"),
    ]

    operations = [
        migrations.RunPython(reset_everyone_to_p3_default, migrations.RunPython.noop),
    ]
