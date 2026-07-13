from django.db import migrations, models

# Serves the claim query's cross-run schema-ordering gate: "is there an older
# non-terminal batch of a different run for this (team_id, schema_id)?" The
# predicate mirrors the gate's non-terminal state list exactly so the planner
# can use the partial index.
#
# sourcebatch is a partitioned parent, so CREATE INDEX CONCURRENTLY is not
# possible — plain creation follows this app's 0006 precedent (and the queue's
# low volume); lock_timeout keeps a blocked attempt from queueing behind long
# claim queries (bin/migrate retries). Guarded with to_regclass so the
# migration no-ops on DBs without the sourcebatch table. One statement per
# execute() and no PL/pgSQL, so it applies against Postgres-wire targets that
# parse a single statement at a time.

_INDEX_NAME = "sb_schema_order_idx"
_CREATE_INDEX_SQL = f"""
    CREATE INDEX IF NOT EXISTS {_INDEX_NAME}
        ON sourcebatch (team_id, schema_id, created_at)
        WHERE latest_state IN ('pending', 'waiting', 'waiting_retry', 'executing')
"""


def _sourcebatch_exists(schema_editor) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.sourcebatch')")
        row = cursor.fetchone()
    return row is not None and row[0] is not None


def _create_index(apps, schema_editor):
    if not _sourcebatch_exists(schema_editor):
        return
    schema_editor.execute("SET LOCAL lock_timeout = '5s'")
    schema_editor.execute(_CREATE_INDEX_SQL)


def _drop_index(apps, schema_editor):
    if not _sourcebatch_exists(schema_editor):
        return
    schema_editor.execute("SET LOCAL lock_timeout = '5s'")
    schema_editor.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0006_sourcebatch_latest_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="sourcebatch",
                    index=models.Index(
                        condition=models.Q(("latest_state__in", ["pending", "waiting", "waiting_retry", "executing"])),
                        fields=["team_id", "schema_id", "created_at"],
                        name="sb_schema_order_idx",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_create_index, _drop_index),
            ],
        ),
    ]
