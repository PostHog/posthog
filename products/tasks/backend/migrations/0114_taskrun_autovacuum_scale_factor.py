from django.db import migrations

# Every task run rewrites the wide `state` and `output` JSONB columns many times through the
# locked read-modify-write helpers, and `updated_at` is both indexed and `auto_now`, so no update
# can take the heap-only tuple path: each one writes a new heap tuple plus entries in all the
# indexes. Nothing hard-deletes rows either, so the dead tuples only accumulate.
# The global scale factor of 0.1 makes autovacuum wait for 10% dead tuples on a table with that
# churn, which is a large steady-state bloat load on the index scans behind the run list and the
# PR webhook lookups. 0.02 keeps those scans on live tuples, and the matching analyze factor keeps
# the planner statistics current for the partial indexes.
#
# SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the run writes.
TABLE = "posthog_task_run"
SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0113_task_team_live_list_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Fail fast rather than queue: this waits behind an in-progress autovacuum
                # on the same table, and a retry is cheaper than holding the lock request.
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} SET ("
                f"autovacuum_vacuum_scale_factor = {SCALE_FACTOR}, "
                f"autovacuum_analyze_scale_factor = {SCALE_FACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)",
            ],
        ),
    ]
