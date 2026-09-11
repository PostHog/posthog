from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0128_open_pull_request_ready_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
