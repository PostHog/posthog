from django.db import migrations

# The table inherits the global scale factors, 0.2 for inserts and 0.1 for dead tuples. At its row
# count autovacuum then waits days between passes, and until a pass runs the recently written pages
# are not all-visible. Those are the pages the flakiness reads cover, so their index-only scans fall
# back to a heap fetch per row. 0.02 matches the other tuned product tables. An insert-triggered pass
# has no dead tuples to clean from the indexes, so it costs little more than the heap pages it visits.
#
# SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the snapshot writes.
TABLE = "visual_review_runsnapshot"
SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0019_runsnapshot_snapshot_run_result_reason"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Fail fast rather than queue: this waits behind an in-progress autovacuum
                # on the same table, and a retry is cheaper than holding the lock request.
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} SET ("
                f"autovacuum_vacuum_scale_factor = {SCALE_FACTOR}, "
                f"autovacuum_vacuum_insert_scale_factor = {SCALE_FACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} RESET (autovacuum_vacuum_scale_factor, autovacuum_vacuum_insert_scale_factor)",
            ],
        ),
    ]
