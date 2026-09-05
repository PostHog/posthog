from django.db import migrations

# The table inherits the global autovacuum_vacuum_scale_factor of 0.1, so autovacuum waits for
# a very large number of dead tuples before it runs. The table carries constant delete and
# update churn: cymbal deletes the resolution results whenever a symbol set saves new data, and
# symbol set cleanup deletes the unresolved frames and then sets `symbol_set_id` to NULL on the
# rows that survive. 0.02 matches the value migration 0023 set on the symbol set table, which
# lowers the trigger enough to matter while keeping the extra vacuum passes affordable.
TABLE = "posthog_errortrackingstackframe"
SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0032_drop_orphaned_stackframe_team_raw_id_idx"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Fail fast rather than queue: this waits behind an in-progress autovacuum
                # on the same table, and a retry is cheaper than holding the lock request.
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} SET (autovacuum_vacuum_scale_factor = {SCALE_FACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} RESET (autovacuum_vacuum_scale_factor)",
            ],
        ),
    ]
