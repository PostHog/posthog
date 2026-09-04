from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0114_signalscoutnote_reviewer_correction_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
