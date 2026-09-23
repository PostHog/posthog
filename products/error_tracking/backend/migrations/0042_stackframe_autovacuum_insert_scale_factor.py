from django.db import migrations

# The source maps recommendation counts each team's JavaScript frames from the last 24 hours.
# et_frame_team_created_js_idx covers that count, but an index-only scan still visits the heap
# for every row on a page the visibility map does not mark all-visible, and this table is
# insert-hot: the freshest 24 hours is exactly the part the map never covers. At the default
# insert scale factor of 0.2 a table this large waits for 20% growth before an insert-driven
# autovacuum runs, so the count pays a heap visit per recent row. 0.005 keeps the map close to
# the write head. An insert-driven vacuum skips all-visible pages and skips the index pass when
# it finds no dead tuples, so the extra work stays proportional to the new pages.
TABLE = "posthog_errortrackingstackframe"
INSERT_SCALE_FACTOR = 0.005


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0041_errortrackingalertdestination_consecutive_failures_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Fail fast rather than queue: this waits behind an in-progress autovacuum
                # on the same table, and a retry is cheaper than holding the lock request.
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} SET (autovacuum_vacuum_insert_scale_factor = {INSERT_SCALE_FACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} RESET (autovacuum_vacuum_insert_scale_factor)",
            ],
        ),
    ]
