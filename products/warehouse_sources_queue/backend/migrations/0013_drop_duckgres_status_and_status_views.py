from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0012_drop_duckgres_sink_tables"),
    ]

    # No queue code reads these. sourcebatchduckgresstatus has no foreign keys, so a plain
    # DROP TABLE locks only its own partitions. The view goes first because it depends on it.
    operations = [
        migrations.RunSQL(
            sql=[
                "DROP VIEW IF EXISTS v_latest_source_batch_duckgres_status",
                "DROP TABLE IF EXISTS sourcebatchduckgresstatus",
                "DROP VIEW IF EXISTS v_latest_source_batch_status",
            ],
            reverse_sql=[
                """
                CREATE VIEW v_latest_source_batch_status AS
                SELECT DISTINCT ON (batch_id) *
                FROM sourcebatchstatus
                ORDER BY batch_id ASC, created_at DESC, id DESC
                """,
            ],
        ),
    ]
