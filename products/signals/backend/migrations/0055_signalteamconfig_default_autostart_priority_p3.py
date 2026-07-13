from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0054_alter_signalsourceconfig_source_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalteamconfig",
            name="default_autostart_priority",
            field=models.CharField(
                choices=[("P0", "P0"), ("P1", "P1"), ("P2", "P2"), ("P3", "P3"), ("P4", "P4")],
                default="P3",
                max_length=2,
            ),
        ),
    ]
