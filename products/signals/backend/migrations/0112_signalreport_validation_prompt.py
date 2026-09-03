from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0111_signalreport_signals_researched"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
