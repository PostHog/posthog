from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0265_signalscoutmessage"),
    ]

    operations = [
        migrations.AddField(
            model_name="anomalyscoringstate",
            name="scoring",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
