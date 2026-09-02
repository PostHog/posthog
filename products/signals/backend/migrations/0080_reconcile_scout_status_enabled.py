from django.db import migrations


def reconcile_enabled_wins(apps, schema_editor):
    # Re-runs 0078's enabled-wins reconciliation over rows old instances drifted during the
    # 0077 rollout window (enabled-only writes from pods that predated the dual-write land
    # after the backfill). `enabled` carries the operator's intent for any mismatch: no
    # system writer existed before the constraints in 0081, so a disagreeing row can only be
    # a human toggle that missed the `status` side. Small table, plain UPDATEs.
    SignalScoutConfig = apps.get_model("signals", "SignalScoutConfig")
    manager = SignalScoutConfig._default_manager
    manager.filter(enabled=False, status__in=["active", "pending_pause"]).update(
        status="paused_by_user", pause_reason=None
    )
    manager.filter(enabled=True, status__in=["paused_by_system", "paused_by_user"]).update(
        status="active", pause_reason=None
    )
    # Reason coherence for 0081's second constraint: a reason on a runnable/user-paused row is
    # stray; a reasonless warning is meaningless (runnable anyway); a reasonless system pause
    # can only predate system writers, so it reads as a human's off-switch.
    manager.filter(status__in=["active", "paused_by_user"], pause_reason__isnull=False).update(pause_reason=None)
    manager.filter(status="pending_pause", pause_reason__isnull=True).update(status="active")
    manager.filter(status="paused_by_system", pause_reason__isnull=True).update(status="paused_by_user")


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0079_signalscoutconfig_consecutive_failure_count"),
    ]

    operations = [
        migrations.RunPython(reconcile_enabled_wins, reverse_code=migrations.RunPython.noop),
    ]
