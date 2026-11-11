from django.db import migrations

# The table is small, but every scout run rewrites its rows: the coordinator stamps `last_run_at`
# on each dispatch, the runner counts failed runs in `consecutive_failure_count`, and status changes
# and rubric saves add more updates. The global scale factor of 0.1 lets dead tuples build up
# between passes, which pganalyze flags as insufficient vacuuming. 0.02 matches the other tuned
# product tables, and the matching analyze factor keeps the planner statistics current.
#
# SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the scout config writes.
TABLE = "signals_signalscoutconfig"
SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0177_backfill_scout_notebook_write"),
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
