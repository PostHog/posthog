from django.db import migrations, models

# Guarded with to_regclass so the migration no-ops on DBs without the sourcebatch table.
_CREATE_INDEX_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS sb_run_uuid_bi_idx
            ON sourcebatch (run_uuid, batch_index);
    END IF;
END
$$;
"""

_DROP_INDEX_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        DROP INDEX IF EXISTS sb_run_uuid_bi_idx;
    END IF;
END
$$;
"""


def _create_index(apps, schema_editor):
    schema_editor.execute(_CREATE_INDEX_SQL)


def _drop_index(apps, schema_editor):
    schema_editor.execute(_DROP_INDEX_SQL)


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
