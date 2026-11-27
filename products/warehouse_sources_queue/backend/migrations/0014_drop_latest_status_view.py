from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0013_restore_sourcebatch_failed_changed_idx"),
    ]

    operations = [
        migrations.RunSQL(
            # A session that is reading the view holds a lock that DROP VIEW waits for.
            # The timeout makes the migration fail and retry instead of waiting without limit.
            sql=[
                "SET LOCAL lock_timeout = '5s'",
                "DROP VIEW IF EXISTS v_latest_source_batch_status",
            ],
            # Same definition as 0001_initial, so the reverse puts back exactly what this drops.
            reverse_sql="""
                CREATE OR REPLACE VIEW v_latest_source_batch_status AS
                SELECT DISTINCT ON (batch_id) *
                FROM sourcebatchstatus
                ORDER BY batch_id ASC, created_at DESC, id DESC
            """,
        ),
    ]
