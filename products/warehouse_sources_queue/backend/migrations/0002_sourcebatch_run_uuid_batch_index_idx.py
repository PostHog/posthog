from django.db import migrations, models


def _create_index(apps, schema_editor):
    schema_editor.execute("CREATE INDEX IF NOT EXISTS sb_run_uuid_bi_idx ON sourcebatch (run_uuid, batch_index);")


def _drop_index(apps, schema_editor):
    schema_editor.execute("DROP INDEX IF EXISTS sb_run_uuid_bi_idx;")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="sourcebatch",
                    index=models.Index(
                        fields=["run_uuid", "batch_index"],
                        name="sb_run_uuid_bi_idx",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_create_index, _drop_index),
            ],
        ),
    ]
