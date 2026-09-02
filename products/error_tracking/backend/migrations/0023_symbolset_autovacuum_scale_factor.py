from django.db import migrations

# The table inherits the global autovacuum_vacuum_scale_factor of 0.1. At its current row
# count that means autovacuum waits for tens of millions of dead tuples before running, so
# the table carries a large steady-state bloat load from its delete and update churn.
# 0.02 is a deliberately conservative first step: it lowers the trigger enough to matter
# while keeping the extra vacuum passes affordable on a table with six indexes.
TABLE = "posthog_errortrackingsymbolset"
SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0022_drop_redundant_symbolset_team_ref_idx"),
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
