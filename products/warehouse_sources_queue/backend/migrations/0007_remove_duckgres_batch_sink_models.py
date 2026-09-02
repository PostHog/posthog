from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0006_sourcebatch_latest_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="SourceBatchDuckgresApply",
                ),
                migrations.DeleteModel(
                    name="SourceBatchDuckgresStatus",
                ),
                migrations.DeleteModel(
                    name="SourceDuckgresGroupLease",
                ),
            ],
            database_operations=[],
        ),
    ]
