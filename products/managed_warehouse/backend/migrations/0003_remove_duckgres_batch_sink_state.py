from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("managed_warehouse", "0002_managedwarehousesourcejob"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="duckgresserver",
                    name="sink_max_concurrency",
                ),
                migrations.DeleteModel(
                    name="DuckgresSinkSchemaState",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE posthog_duckgresserver ALTER COLUMN sink_max_concurrency SET DEFAULT 4;",
                    reverse_sql="ALTER TABLE posthog_duckgresserver ALTER COLUMN sink_max_concurrency DROP DEFAULT;",
                ),
            ],
        ),
    ]
