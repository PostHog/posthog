from django.db import migrations

# The reviewer-suggestion cache is churned by three write paths and pruned by none of them.
# `get_area_activity` stamps `last_used_at` on every row it reads, so a read is an update.
# `rebuild_repository_activity` rewrites the `contributors` JSON and `refreshed_at` for every
# area row of a repository at once, and a repository has many area rows because each commit is
# indexed at its own area, every parent area, and the repository root. The weekly warm-up task
# force-rebuilds every warm repository, and its one delete pass only drops long-idle rows.
# So dead tuples accumulate for a week at a time on a small table, where the inherited scale
# factor of 0.1 makes autovacuum wait far longer than that turnover deserves. 0.02 keeps the
# reviewer suggestion reads on live tuples, and the matching analyze factor keeps the planner
# statistics current.
#
# The lower fillfactor leaves each page free space for a new tuple version. No update on this
# table touches an indexed column, so with that headroom the updates leave no index work behind.
# It applies to pages filled after this runs, not to existing ones.
#
# SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the cache's writes.
TABLE = "signals_signalrepositoryareaactivity"
SCALE_FACTOR = 0.02
FILLFACTOR = 90


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0140_signalreportcheck_soak_minutes_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Fail fast rather than queue: this waits behind an in-progress autovacuum
                # on the same table, and a retry is cheaper than holding the lock request.
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} SET ("
                f"autovacuum_vacuum_scale_factor = {SCALE_FACTOR}, "
                f"autovacuum_analyze_scale_factor = {SCALE_FACTOR}, "
                f"fillfactor = {FILLFACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} RESET ("
                "autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor, fillfactor)",
            ],
        ),
    ]
