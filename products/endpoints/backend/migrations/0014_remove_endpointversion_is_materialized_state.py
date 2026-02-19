from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0013_add_endpointversion_is_active"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="endpointversion",
                    name="is_materialized",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE endpoints_endpointversion ALTER COLUMN is_materialized SET DEFAULT false",
                    reverse_sql="ALTER TABLE endpoints_endpointversion ALTER COLUMN is_materialized DROP DEFAULT",
                ),
            ],
        ),
    ]
