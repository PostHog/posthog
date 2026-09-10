from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0123_alter_signalsourceconfig_team"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
