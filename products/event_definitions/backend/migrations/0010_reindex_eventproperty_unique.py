from django.db import migrations


class Migration(migrations.Migration):
    """REINDEX posthog_event_property_unique_proj_event_property — rebuild 1100 GB / 1629 GB unique constraint.

    The unique constraint is the largest artifact on the table. Audit confirmed the size is bloat plus
    string-column key bytes, NOT coalesce expression overhead — so REINDEX is the correct lever, not
    changing the expression to (team_id, event, property). Multi-team-per-project semantics require
    the coalesce; migration 0532 explicitly deleted child-team rows to enable the project rollup.

    Estimated reclaim: ~400-600 GB US, ~800-1000 GB EU.

    No model state change — purely a physical operation. The unique constraint definition in the
    model stays identical.

    Aurora-specific risks (same shape as PR 2's REINDEX of (team_id, event), but ~1.4x larger):
    WAL throughput, AuroraReplicaLag, IOPS, buffer cache eviction. Disk-full is NOT a concern.

    Sequencing: only run AFTER the Tier 2 REINDEX (0009) has stabilized. Reduces concurrent
    index-update pressure on the table during this longer rebuild.

    Pre-deploy:
    - Confirm AuroraReplicaLagMaximum p99 < 50 ms baseline.
    - Schedule the lowest-write window. Sustained INSERT load from property-defs-rs slows the swap.
    - Don't run prod-us and prod-eu simultaneously.
    - SET max_parallel_maintenance_workers = 8 is session-scoped — Aurora default is 2,
      so 8 parallel B-tree builders give a real ~3-4x speedup. maintenance_work_mem is
      intentionally NOT set here: Aurora cluster defaults (8.12 GB US / 6.09 GB EU) already
      exceed any safe override we'd pick, so we inherit them. Larger sort buffer = less
      disk-spill = shorter wall-clock = shorter window of WAL/IOPS/buffer-cache disturbance.

    Abort: pg_cancel_backend on this session, then DROP INDEX CONCURRENTLY IF EXISTS
    posthog_event_property_unique_proj_event_property_ccnew. Original constraint index untouched.
    """

    atomic = False

    dependencies = [
        ("event_definitions", "0009_reindex_eventproperty_team_event"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "SET max_parallel_maintenance_workers = 8",
                "REINDEX INDEX CONCURRENTLY posthog_event_property_unique_proj_event_property",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
