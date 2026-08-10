from django.db import migrations, models

# Guarded with to_regclass so the migration no-ops on DBs without the sourcebatch
# table, following 0006. The run-gate partial index gains 'superseded' in its
# predicate; a predicate can't be altered in place, so the successor index is
# created first (under a new name) and the old one dropped after, so the claim
# gates never lose index coverage. Plain (non-concurrent) creation follows this
# app's 0002/0006 precedent; lock_timeout keeps a blocked attempt from queueing
# behind long claim queries (bin/migrate retries). The choices change on
# latest_state/job_state is state-only — both are plain varchars.
_FORWARD_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        CREATE INDEX IF NOT EXISTS sb_run_gate2_idx
            ON sourcebatch (run_uuid, latest_state, batch_index)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed', 'superseded');
        DROP INDEX IF EXISTS sb_run_gate_idx;
    END IF;
END
$$;
"""

_REVERSE_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sourcebatch') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        CREATE INDEX IF NOT EXISTS sb_run_gate_idx
            ON sourcebatch (run_uuid, latest_state, batch_index)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed');
        DROP INDEX IF EXISTS sb_run_gate2_idx;
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
                migrations.AlterField(
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
                            ("superseded", "superseded"),
                        ],
                        db_default="pending",
                        default="pending",
                        max_length=32,
                    ),
                ),
                migrations.AlterField(
                    model_name="sourcebatchstatus",
                    name="job_state",
                    field=models.CharField(
                        choices=[
                            ("waiting", "waiting"),
                            ("executing", "executing"),
                            ("succeeded", "succeeded"),
                            ("waiting_retry", "waiting_retry"),
                            ("failed", "failed"),
                            ("superseded", "superseded"),
                        ],
                        max_length=32,
                    ),
                ),
                migrations.RemoveIndex(
                    model_name="sourcebatch",
                    name="sb_run_gate_idx",
                ),
                migrations.AddIndex(
                    model_name="sourcebatch",
                    index=models.Index(
                        condition=models.Q(
                            ("latest_state__in", ["executing", "waiting_retry", "failed", "superseded"])
                        ),
                        fields=["run_uuid", "latest_state", "batch_index"],
                        name="sb_run_gate2_idx",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_forward, _reverse),
            ],
        ),
    ]
