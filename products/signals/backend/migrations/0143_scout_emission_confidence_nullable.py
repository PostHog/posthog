from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0142_untrack_signalscoutemission_weight"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalscoutemission",
            name="confidence",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
