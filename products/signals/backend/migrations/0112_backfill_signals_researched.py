from django.db import migrations
from django.db.models import F, IntegerField, Value
from django.db.models.functions import Greatest

# The status whose promotion rule reads the new column. `potential` and `candidate` promote without
# it, `pending_input` and the terminal statuses never re-promote, so only `ready` needs a seed.
_RESEARCHED = "ready"
# The constant every `candidate -> in_progress` transition adds to `signal_count` when it stamps
# `signals_at_run`. Spelled out rather than imported because a migration must keep describing the
# schema as it was the day it ran, whatever the model says later.
_SIGNALS_AT_RUN_INCREMENT = 3
_BATCH = 500


def backfill_signals_researched(apps, schema_editor):
    """Seed the completed-pass count for reports that were researched before the column existed.

    Left at 0 a `ready` report reads as never researched, so the first signal to arrive would put it
    at bucket 1 and re-research it. Every report the inbox is already carrying would research again
    on its next signal, which is the opposite of what the bucket schedule is for.

    `signals_at_run` is the only record of what a past pass covered: every run stamps it as
    `signal_count + 3` on the way into `in_progress`, so subtracting that constant recovers the
    count the run started on. A `ready` report always carries the stamp from a run rather than from
    a snooze, because snoozing moves a report to `potential` and it can only return to `ready`
    through another run.

    The reconstruction is one run late for a report whose most recent run stamped `signals_at_run`
    and then paused on the quota gate instead of completing: such a report reads as having
    researched up to 3 signals more than it did, which can carry it past a bucket it still owed.
    Bounded, and it only affects reports that were mid-pause the day this ran.
    """
    SignalReport = apps.get_model("signals", "SignalReport")

    queryset = SignalReport._default_manager.filter(status=_RESEARCHED).order_by("id")
    # Paged by id rather than by "still 0", because a report whose last run started on 3 signals or
    # fewer is seeded back to 0 and would otherwise be handed out forever.
    last_id = None
    while True:
        page = queryset if last_id is None else queryset.filter(id__gt=last_id)
        batch = list(page.values_list("id", flat=True)[:_BATCH])
        if not batch:
            return
        last_id = batch[-1]
        SignalReport._default_manager.filter(id__in=batch).update(
            signals_researched=Greatest(
                F("signals_at_run") - _SIGNALS_AT_RUN_INCREMENT,
                Value(0),
                output_field=IntegerField(),
            )
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0111_signalreport_signals_researched"),
    ]

    operations = [
        migrations.RunPython(backfill_signals_researched, migrations.RunPython.noop, elidable=True),
    ]
