from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0198_warehouse_migration"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="ExternalDataSourceInputsBackup")],
            database_operations=[],
        ),
    ]
