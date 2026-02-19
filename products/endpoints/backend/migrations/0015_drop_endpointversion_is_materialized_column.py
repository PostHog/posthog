from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0014_remove_endpointversion_is_materialized_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE endpoints_endpointversion DROP COLUMN IF EXISTS is_materialized",
                    reverse_sql="ALTER TABLE endpoints_endpointversion ADD COLUMN is_materialized boolean NOT NULL DEFAULT false",
                ),
            ],
        ),
    ]
