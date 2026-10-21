from django.db import migrations, models

# A nullable ADD COLUMN with no default is metadata-only, but it still takes a brief
# ACCESS EXCLUSIVE lock. lock_timeout keeps a blocked attempt from queueing behind the
# scheduler's tick transaction (bin/migrate retries). The table is not partitioned.
_ADD_COLUMN_SQL = """
DO $$
BEGIN
    IF to_regclass('public.queueschedulerdecision') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE queueschedulerdecision ADD COLUMN IF NOT EXISTS job_id uuid NULL;
    END IF;
END
$$;
"""

_DROP_COLUMN_SQL = """
DO $$
BEGIN
    IF to_regclass('public.queueschedulerdecision') IS NOT NULL THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE queueschedulerdecision DROP COLUMN IF EXISTS job_id;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0012_scheduler_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="queueschedulerdecision",
                    name="job_id",
                    field=models.UUIDField(blank=True, null=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(sql=_ADD_COLUMN_SQL, reverse_sql=_DROP_COLUMN_SQL),
            ],
        ),
    ]
