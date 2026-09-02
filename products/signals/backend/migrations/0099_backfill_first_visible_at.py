from django.db import migrations
from django.db.models import F, Q


def backfill_first_visible_at(apps, schema_editor):
    """Stamp reports that were already user-visible before first_visible_at existed.

    The set-once guard in transition_to treats NULL as "never seen", so an unstamped pre-existing
    report re-entering ready/pending_input (reopen on new signals, restore from archive) would be
    stamped with the current time and wrongly consume a max_reports_per_day slot that day. Rows
    that provably surfaced before — currently visible, resolved (only reachable from a visible
    status), or suppressed away from one of those — get their created_at, which on every day after
    this migration precedes the day boundary, so a backfilled report never counts. The lone
    exception is a report created earlier on the migration day whose team also enables the limit
    that same local day: created_at then falls inside the current day and the report counts against
    it, a bounded overshoot that clears at the next local midnight, matching the in-flight overshoot
    the limit already tolerates. Updated in batches so the whole backlog isn't row-locked in one
    statement.
    """
    SignalReport = apps.get_model("signals", "SignalReport")
    visible = ["ready", "pending_input", "resolved"]
    unstamped = SignalReport.objects.filter(first_visible_at__isnull=True).filter(
        Q(status__in=visible) | Q(status="suppressed", status_before_suppression__in=visible)
    )
    while True:
        batch = list(unstamped.values_list("id", flat=True)[:500])
        if not batch:
            break
        SignalReport.objects.filter(id__in=batch).update(first_visible_at=F("created_at"))


class Migration(migrations.Migration):
    # Non-atomic so each batch's UPDATE commits and releases its row locks as it goes. The default
    # wrapping transaction would instead hold every updated row locked until the whole backfill
    # committed, which is the lock buildup the batching is meant to avoid. Safe to resume after a
    # partial run because each pass only ever selects rows that are still unstamped.
    atomic = False

    dependencies = [
        ("signals", "0098_signalreport_first_visible_index"),
    ]

    # Reverse is a noop: clearing the stamps would recreate the miscount this backfill closes.
    operations = [
        migrations.RunPython(backfill_first_visible_at, migrations.RunPython.noop, elidable=True),
    ]
