from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

# Rebuilds 0008's index on databases where it is missing. Django state already has
# the index from 0008, so this migration changes the database only.
INDEX_NAME = "sb_failed_changed_idx"
_INDEX_COLUMNS = "(state_changed_at)"
_INDEX_PREDICATE = "latest_state = 'failed'"

# Same build as 0008 and 0009: an invalid ON ONLY parent, then one CONCURRENTLY
# index per partition, attached one by one, so the claim path is never locked out.
_PARENT_INDEX_SQL = f"""
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        CREATE INDEX IF NOT EXISTS {INDEX_NAME}
            ON ONLY sourcebatch {_INDEX_COLUMNS}
            WHERE {_INDEX_PREDICATE};
    END IF;
END
$$;
"""

_PARTITIONS_SQL = """
    SELECT c.relname
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    WHERE i.inhparent = 'public.sourcebatch'::regclass
    ORDER BY c.relname
"""

# Matched by OID, not by name: partitions created after the parent index exists get
# a child index under a name Postgres generates, and a second ATTACH would fail.
_PARTITION_ATTACHED_SQL = f"""
    SELECT EXISTS (
        SELECT 1
        FROM pg_inherits pi
        JOIN pg_index ci ON ci.indexrelid = pi.inhrelid
        WHERE pi.inhparent = 'public.{INDEX_NAME}'::regclass
          AND ci.indrelid = %s::regclass
    )
"""

_INDEX_VALID_SQL = """
    SELECT i.indisvalid
    FROM pg_class c
    JOIN pg_index i ON i.indexrelid = c.oid
    WHERE c.relname = %s
"""


def _sourcebatch_exists(schema_editor) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.sourcebatch') IS NOT NULL")
        row = cursor.fetchone()
    return bool(row and row[0])


def _partitions(schema_editor) -> list[str]:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(_PARTITIONS_SQL)
        return [row[0] for row in cursor.fetchall()]


def _partition_attached(schema_editor, partition: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(_PARTITION_ATTACHED_SQL, [f'public."{partition}"'])
        row = cursor.fetchone()
    return bool(row and row[0])


def _index_valid(schema_editor, index_name: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(_INDEX_VALID_SQL, [index_name])
        row = cursor.fetchone()
    return bool(row and row[0])


def _disable_timeouts(schema_editor) -> None:
    # A cancelled CONCURRENTLY build leaves an invalid index that IF NOT EXISTS
    # would skip past on every retry, so these builds must not be interruptible.
    schema_editor.execute("SET lock_timeout = 0")
    schema_editor.execute("SET statement_timeout = 0")


def _forward(apps, schema_editor):
    schema_editor.execute(_PARENT_INDEX_SQL)
    if not _sourcebatch_exists(schema_editor):
        return

    _disable_timeouts(schema_editor)
    for partition in _partitions(schema_editor):
        if _partition_attached(schema_editor, partition):
            continue
        index_name = f"{partition}_{INDEX_NAME}"
        if not _index_valid(schema_editor, index_name):
            schema_editor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"')
            logger.info("sourcebatch_partition_index_build", partition=partition, index_name=index_name)
            schema_editor.execute(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
                f'ON "{partition}" {_INDEX_COLUMNS} WHERE {_INDEX_PREDICATE}'
            )
        schema_editor.execute(f'ALTER INDEX {INDEX_NAME} ATTACH PARTITION "{index_name}"')


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    atomic = False

    dependencies = [
        ("warehouse_sources_queue", "0012_scheduler_state"),
    ]

    operations = [
        # Reverse is a no-op because 0008 owns this index; its reverse drops it.
        migrations.RunPython(_forward, migrations.RunPython.noop),
    ]
