from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("managed_warehouse", "0001_migrate_managed_warehouse_models"),
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
            database_operations=[],
        ),
    ]
