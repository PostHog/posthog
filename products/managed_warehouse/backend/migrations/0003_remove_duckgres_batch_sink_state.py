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
            database_operations=[],
        ),
    ]
