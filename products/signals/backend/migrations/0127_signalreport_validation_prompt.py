from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0126_signalteamconfig_issue_tracking_config_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
