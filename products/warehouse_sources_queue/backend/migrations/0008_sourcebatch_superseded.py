from django.db import migrations, models

import structlog

logger = structlog.get_logger(__name__)

INDEX_NAME = "sb_failed_changed_idx"
_INDEX_COLUMNS = "(state_changed_at)"
_INDEX_PREDICATE = "latest_state = 'failed'"

# Guarded with to_regclass so the migration no-ops on DBs without the sourcebatch
# table, following 0006. ADD COLUMN ... DEFAULT false is metadata-only on PG11+,
# but still takes a brief ACCESS EXCLUSIVE lock on the parent and every child —
# lock_timeout keeps a blocked attempt from queueing behind long claim queries
# (bin/migrate retries). The raw DEFAULT is load-bearing: producer INSERTs list
# their columns explicitly and never mention superseded.
#
# ON ONLY creates the parent index as metadata alone, leaving it invalid until
# every partition has a matching index attached. Building those per partition
# with CONCURRENTLY is the only way to add this index without locking writes out
# of the batch table for the length of the build: CONCURRENTLY is not supported
# on a partitioned parent, and a plain build there recurses into every partition
# under a lock that blocks the claim path this PR exists to protect.
_ADD_COLUMN_SQL = f"""
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE sourcebatch ADD COLUMN IF NOT EXISTS superseded boolean NOT NULL DEFAULT false;
        CREATE INDEX IF NOT EXISTS {INDEX_NAME}
            ON ONLY sourcebatch {_INDEX_COLUMNS}
            WHERE {_INDEX_PREDICATE};
    END IF;
END
$$;
"""

_DROP_COLUMN_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE sourcebatch DROP COLUMN IF EXISTS superseded;
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

# indisvalid is false while a CONCURRENTLY build is unfinished or was cancelled;
# the pg_inherits probe says whether the child index is already attached to the
# parent, which is what makes the whole loop re-runnable under bin/migrate retries.
_INDEX_STATE_SQL = """
    SELECT i.indisvalid, EXISTS (SELECT 1 FROM pg_inherits pi WHERE pi.inhrelid = c.oid)
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


def _index_state(schema_editor, index_name: str) -> tuple[bool, bool]:
    """(exists_and_valid, attached_to_parent) for a per-partition index."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(_INDEX_STATE_SQL, [index_name])
        row = cursor.fetchone()
    if row is None:
        return False, False
    return bool(row[0]), bool(row[1])


def _disable_timeouts(schema_editor) -> None:
    # A cancelled CONCURRENTLY build leaves an invalid index that IF NOT EXISTS
    # would skip past on every retry, so these builds must not be interruptible.
    schema_editor.execute("SET lock_timeout = 0")
    schema_editor.execute("SET statement_timeout = 0")


def _forward(apps, schema_editor):
    schema_editor.execute(_ADD_COLUMN_SQL)
    if not _sourcebatch_exists(schema_editor):
        return

    _disable_timeouts(schema_editor)
    for partition in _partitions(schema_editor):
        index_name = f"{partition}_{INDEX_NAME}"
        valid, attached = _index_state(schema_editor, index_name)
        if attached:
            continue
        if not valid:
            # Either absent, or an invalid leftover from an interrupted build.
            schema_editor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"')
            logger.info("sourcebatch_partition_index_build", partition=partition, index_name=index_name)
            schema_editor.execute(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
                f'ON "{partition}" {_INDEX_COLUMNS} WHERE {_INDEX_PREDICATE}'
            )
        # Attaching the last partition is what flips the parent index to valid.
        schema_editor.execute(f'ALTER INDEX {INDEX_NAME} ATTACH PARTITION "{index_name}"')


def _reverse(apps, schema_editor):
    if _sourcebatch_exists(schema_editor):
        _disable_timeouts(schema_editor)
        # Dropping the parent takes every attached child with it; the loop then
        # clears children a partial forward run created but never attached.
        schema_editor.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
        for partition in _partitions(schema_editor):
            schema_editor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{partition}_{INDEX_NAME}"')
    schema_editor.execute(_DROP_COLUMN_SQL)


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    atomic = False

    dependencies = [
        ("warehouse_sources_queue", "0007_remove_duckgres_batch_sink_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="sourcebatch",
                    name="superseded",
                    field=models.BooleanField(db_default=False, default=False),
                ),
                migrations.AddIndex(
                    model_name="sourcebatch",
                    index=models.Index(
                        condition=models.Q(("latest_state", "failed")),
                        fields=["state_changed_at"],
                        name="sb_failed_changed_idx",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_forward, _reverse),
            ],
        ),
    ]
