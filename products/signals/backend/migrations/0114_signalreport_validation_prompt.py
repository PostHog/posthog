from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0113_signalreport_inbox_notified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
