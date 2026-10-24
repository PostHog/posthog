from django.db import migrations, models

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0199_anomalyscoringstate"),
    ]

    operations = [
        # The column stays until a later drop. New rows do not name it, so it needs a database default.
        untrack_field(
            "anomalyscoringstate",
            "series",
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE signals_anomalyscoringstate ALTER COLUMN series SET DEFAULT '{}'::jsonb",
                    reverse_sql="ALTER TABLE signals_anomalyscoringstate ALTER COLUMN series DROP DEFAULT",
                )
            ],
        ),
        migrations.AddField(
            model_name="anomalyscoringstate",
            name="artifact_key",
            field=models.CharField(default="", max_length=255),
        ),
        migrations.AddField(
            model_name="anomalyscoringstate",
            name="artifact_sha256",
            field=models.CharField(default="", max_length=64),
        ),
        migrations.AddField(
            model_name="anomalyscoringstate",
            name="series_keys",
            field=models.JSONField(default=list),
        ),
    ]
