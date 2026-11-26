from django.db import migrations

VIEW_NAME = "v_latest_source_batch_status"

# Same definition as 0001_initial, so the reverse puts back exactly what this drops.
_CREATE_VIEW_SQL = f"""
    CREATE VIEW {VIEW_NAME} AS
    SELECT DISTINCT ON (batch_id) *
    FROM sourcebatchstatus
    ORDER BY batch_id ASC, created_at DESC, id DESC
"""


def _drop_view(apps, schema_editor):
    # A session that is reading the view holds a lock that DROP VIEW waits for.
    # The timeout makes the migration fail and retry instead of waiting without limit.
    schema_editor.execute("SET LOCAL lock_timeout = '5s'")
    schema_editor.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")


def _recreate_view(apps, schema_editor):
    schema_editor.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
    schema_editor.execute(_CREATE_VIEW_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0013_restore_sourcebatch_failed_changed_idx"),
    ]

    operations = [
        # RunPython, like the 0001_initial operation that created the view. Django has no
        # state for the view, so there is nothing to remove from migration state.
        migrations.RunPython(_drop_view, _recreate_view),
    ]
