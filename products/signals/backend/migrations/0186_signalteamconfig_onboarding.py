from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0185_signalscoutconfig_last_precheck")]

    operations = [
        migrations.AddField(
            model_name="signalteamconfig",
            name="onboarding",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
