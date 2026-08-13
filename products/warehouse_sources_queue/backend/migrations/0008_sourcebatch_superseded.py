from django.db import migrations, models

# Guarded with to_regclass so the migration no-ops on DBs without the sourcebatch
# table, following 0006. ADD COLUMN ... DEFAULT false is metadata-only on PG11+,
# but still takes a brief ACCESS EXCLUSIVE lock on the parent and every child —
# lock_timeout keeps a blocked attempt from queueing behind long claim queries
# (bin/migrate retries). The raw DEFAULT is load-bearing: producer INSERTs list
# their columns explicitly and never mention superseded. Partial index on the
# parent propagates to all children; plain (non-concurrent) creation follows
# 0002/0006 precedent, and the failed subset it covers is small per partition.
_FORWARD_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE sourcebatch ADD COLUMN IF NOT EXISTS superseded boolean NOT NULL DEFAULT false;
        CREATE INDEX IF NOT EXISTS sb_failed_changed_idx
            ON sourcebatch (state_changed_at)
            WHERE latest_state = 'failed';
    END IF;
END
$$;
"""

_REVERSE_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        DROP INDEX IF EXISTS sb_failed_changed_idx;
        ALTER TABLE sourcebatch DROP COLUMN IF EXISTS superseded;
    END IF;
END
$$;
"""


def _forward(apps, schema_editor):
    schema_editor.execute(_FORWARD_SQL)


def _reverse(apps, schema_editor):
    schema_editor.execute(_REVERSE_SQL)


class Migration(migrations.Migration):
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
