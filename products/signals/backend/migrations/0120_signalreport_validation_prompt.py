from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0119_squash_2026_09_07_schema_addons"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
