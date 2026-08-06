from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0088_signalscoutconfig_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalteamconfig",
            name="autostart_pr_draft",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="signalteamconfig",
            name="autostart_pr_labels",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="signalteamconfig",
            name="autostart_pr_instructions",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
