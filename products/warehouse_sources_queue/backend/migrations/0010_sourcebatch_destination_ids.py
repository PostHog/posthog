from django.db import migrations, models

# Guarded with to_regclass so the migration no-ops on DBs without the sourcebatch table,
# following 0006 and 0008. ADD COLUMN ... DEFAULT is metadata-only on PG11+, but it still
# takes a brief ACCESS EXCLUSIVE lock on the parent and every child — lock_timeout keeps a
# blocked attempt from queueing behind long claim queries (bin/migrate retries). The raw
# DEFAULT is load-bearing: producer INSERTs list their columns explicitly and never mention
# destination_ids, and it is what keeps CDC batches warehouse-only.
_ADD_COLUMN_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE sourcebatch
            ADD COLUMN IF NOT EXISTS destination_ids jsonb NOT NULL DEFAULT '[]'::jsonb;
    END IF;
END
$$;
"""

_DROP_COLUMN_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE sourcebatch DROP COLUMN IF EXISTS destination_ids;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0009_sourcebatch_job_id_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="sourcebatch",
                    name="destination_ids",
                    field=models.JSONField(
                        blank=True,
                        db_default=[],
                        default=list,
                        help_text="ExternalDataDestination ids this batch is delivered to. Empty means the PostHog warehouse only.",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(sql=_ADD_COLUMN_SQL, reverse_sql=_DROP_COLUMN_SQL),
            ],
        ),
    ]
