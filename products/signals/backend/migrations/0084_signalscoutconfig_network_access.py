from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0083_signalscoutconfig_auto_pause_exempt"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscoutconfig",
            name="network_access",
            field=models.CharField(
                choices=[("trusted", "Trusted domains only"), ("full", "Full")],
                db_default="trusted",
                default="trusted",
                max_length=20,
            ),
        ),
    ]
