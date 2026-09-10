from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0121_signalscoutconfig_display_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
