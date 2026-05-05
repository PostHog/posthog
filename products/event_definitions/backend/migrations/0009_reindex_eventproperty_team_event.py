from django.db import migrations


class Migration(migrations.Migration):
    """REINDEX posthog_eve_team_id_22de03_idx — rebuild bloated 802 GB / 1182 GB index at natural size.

    Production cross-team event_screenshots JOIN uses this index for the Nested Loop inner probe
    (verified in prod-us EXPLAIN, May 2026 — planner picks this index even with smaller alternatives
    available). Drop would force costly fallback. REINDEX rebuilds in place at natural ~80 GB / ~120 GB,
    reclaiming ~720 GB US / ~1060 GB EU with zero plan-choice change.

    No model state change — purely a physical operation. The (team_id, event) Index entry stays
    in the model; only its on-disk pages are rewritten.

    Aurora-specific risks: WAL throughput, AuroraReplicaLag, IOPS, buffer cache eviction.
    Disk-full is NOT a concern (Aurora storage auto-grows transparently).

    Pre-deploy:
    - Confirm AuroraReplicaLagMaximum p99 < 50 ms baseline.
    - Schedule low-write window (off-peak property-defs-rs INSERT rate).
    - Don't run prod-us and prod-eu simultaneously.
    - SET max_parallel_maintenance_workers = 8 is session-scoped — Aurora default is 2,
      so 8 parallel B-tree builders give a real ~3-4x speedup. maintenance_work_mem is
      intentionally NOT set here: Aurora cluster defaults (8.12 GB US / 6.09 GB EU) already
      exceed any safe override we'd pick, so we inherit them. Larger sort buffer = less
      disk-spill = shorter wall-clock = shorter window of WAL/IOPS/buffer-cache disturbance.

    Abort: pg_cancel_backend on this session, then DROP INDEX CONCURRENTLY IF EXISTS
    posthog_eve_team_id_22de03_idx_ccnew. Original index untouched.
    """

    atomic = False

    dependencies = [
        ("event_definitions", "0007_drop_eventproperty_team_id_fk_idx"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "SET max_parallel_maintenance_workers = 8",
                "REINDEX INDEX CONCURRENTLY posthog_eve_team_id_22de03_idx",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
