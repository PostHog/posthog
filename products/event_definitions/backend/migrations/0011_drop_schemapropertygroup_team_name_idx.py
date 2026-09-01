from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0010_propertydefinition_warehouse_origin"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="schemapropertygroup",
                    name="schema_pg_team_name_idx",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS schema_pg_team_name_idx",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
