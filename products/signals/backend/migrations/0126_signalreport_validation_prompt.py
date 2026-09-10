from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0125_signalreport_scout_idem_key_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
