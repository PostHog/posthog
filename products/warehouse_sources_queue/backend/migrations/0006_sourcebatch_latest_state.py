from django.db import migrations, models

# Guarded with to_regclass so the migration no-ops on DBs without the sourcebatch
# table. ADD COLUMN ... DEFAULT is metadata-only on PG11+, but it still takes a
# brief ACCESS EXCLUSIVE lock on the parent and every child — lock_timeout keeps a
# blocked attempt from queueing behind long claim queries (bin/migrate retries).
# Partial indexes on the parent propagate to all children; plain (non-concurrent)
# creation follows this app's 0002 precedent and the queue's current low volume.
# The per-child autovacuum tuning keeps the partial indexes from bloating once the
# dual-writes turn state flips into in-place updates.
_FORWARD_SQL = """
DO $$
DECLARE
    part text;
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE sourcebatch ADD COLUMN IF NOT EXISTS latest_state varchar(32) NOT NULL DEFAULT 'pending';
        ALTER TABLE sourcebatch ADD COLUMN IF NOT EXISTS latest_attempt smallint NOT NULL DEFAULT 0;
        ALTER TABLE sourcebatch ADD COLUMN IF NOT EXISTS state_changed_at timestamptz NULL;
        CREATE INDEX IF NOT EXISTS sb_claimable_idx
            ON sourcebatch (team_id, created_at, batch_index)
            WHERE latest_state IN ('pending', 'waiting_retry');
        CREATE INDEX IF NOT EXISTS sb_run_gate_idx
            ON sourcebatch (run_uuid, latest_state, batch_index)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed');
        CREATE INDEX IF NOT EXISTS sb_schema_busy_idx
            ON sourcebatch (team_id, schema_id)
            WHERE latest_state = 'executing';
        FOR part IN
            SELECT inhrelid::regclass::text FROM pg_inherits WHERE inhparent = 'sourcebatch'::regclass
        LOOP
            -- Concatenation, not format(): psycopg scans this whole script for
            -- placeholders, so no percent sign may appear anywhere in it.
            EXECUTE 'ALTER TABLE ' || part
                || ' SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.02)';
        END LOOP;
    END IF;
END
$$;
"""

_REVERSE_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        DROP INDEX IF EXISTS sb_claimable_idx;
        DROP INDEX IF EXISTS sb_run_gate_idx;
        DROP INDEX IF EXISTS sb_schema_busy_idx;
        ALTER TABLE sourcebatch DROP COLUMN IF EXISTS latest_state;
        ALTER TABLE sourcebatch DROP COLUMN IF EXISTS latest_attempt;
        ALTER TABLE sourcebatch DROP COLUMN IF EXISTS state_changed_at;
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
        ("warehouse_sources_queue", "0005_duckgres_group_lease"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="sourcebatch",
                    name="latest_state",
                    field=models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("waiting", "waiting"),
                            ("executing", "executing"),
                            ("succeeded", "succeeded"),
                            ("waiting_retry", "waiting_retry"),
                            ("failed", "failed"),
                        ],
                        db_default="pending",
                        default="pending",
                        max_length=32,
                    ),
                ),
                migrations.AddField(
                    model_name="sourcebatch",
                    name="latest_attempt",
                    field=models.SmallIntegerField(db_default=0, default=0),
                ),
                migrations.AddField(
                    model_name="sourcebatch",
                    name="state_changed_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddIndex(
                    model_name="sourcebatch",
                    index=models.Index(
                        condition=models.Q(("latest_state__in", ["pending", "waiting_retry"])),
                        fields=["team_id", "created_at", "batch_index"],
                        name="sb_claimable_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="sourcebatch",
                    index=models.Index(
                        condition=models.Q(("latest_state__in", ["executing", "waiting_retry", "failed"])),
                        fields=["run_uuid", "latest_state", "batch_index"],
                        name="sb_run_gate_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="sourcebatch",
                    index=models.Index(
                        condition=models.Q(("latest_state", "executing")),
                        fields=["team_id", "schema_id"],
                        name="sb_schema_busy_idx",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_forward, _reverse),
            ],
        ),
    ]
