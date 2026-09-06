from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0116_signalscoutconfig_write_scopes"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
