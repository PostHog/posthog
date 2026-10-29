from django.db import migrations

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
    ]
