from django.db import migrations, models


def bump_default_p0_to_p2(apps, schema_editor):
    """Raise teams still on the old P0 default up to the new P2 default.

    P0 was only ever the auto-created default (there's no UI to pick it), so a row at
    P0 reflects the old default rather than a deliberate choice. Rows set to any other
    priority are left untouched.
    """
    SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")
    SignalTeamConfig.objects.filter(default_autostart_priority="P0").update(default_autostart_priority="P2")


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0034_signalscoutemission"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalteamconfig",
            name="default_autostart_priority",
            field=models.CharField(
                choices=[("P0", "P0"), ("P1", "P1"), ("P2", "P2"), ("P3", "P3"), ("P4", "P4")],
                default="P2",
                max_length=2,
            ),
        ),
        migrations.RunPython(bump_default_p0_to_p2, migrations.RunPython.noop),
    ]
