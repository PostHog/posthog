from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0200_anomalyscoringstate_untrack_series"),
    ]

    operations = [
        migrations.AddField(
            model_name="anomalyscoringstate",
            name="artifact_key",
            field=models.CharField(db_default="", default="", max_length=255),
        ),
        migrations.AddField(
            model_name="anomalyscoringstate",
            name="artifact_sha256",
            field=models.CharField(db_default="", default="", max_length=64),
        ),
        migrations.AddField(
            model_name="anomalyscoringstate",
            name="series_keys",
            field=models.JSONField(db_default=[], default=list),
        ),
    ]
