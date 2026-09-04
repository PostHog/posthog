from django.db import migrations
from django.db.models import DateTimeField, F, OuterRef, Subquery
from django.db.models.functions import Coalesce, Greatest

# The statuses the staleness sweep can archive, mirroring `models.REAPABLE_REPORT_STATUSES`.
# Spelled out rather than imported because a migration must keep describing the schema as it was
# the day it ran, whatever the model says later.
_REAPABLE = ("candidate", "in_progress", "pending_input", "ready")
_BATCH = 500


def _batched_update(queryset, **updates):
    """Apply `updates` in batches so no single statement row-locks the whole backlog."""
    while True:
        batch = list(queryset.values_list("id", flat=True)[:_BATCH])
        if not batch:
            return
        queryset.model._default_manager.filter(id__in=batch).update(**updates)


def backfill_staleness_clocks(apps, schema_editor):
    """Seed both staleness clocks, and opt every team that exists today out of the sweep.

    A null clock has no defensible reading. Left null it means "never touched", which the sweep
    resolves against `created_at` — so every report the inbox has been carrying for months would
    be archived on the first enforcing sweep, on evidence that was never collected rather than on
    evidence of silence.

    Only the reapable statuses are seeded. Everything else reaches one of them through
    `transition_to`, which stamps `last_activity_at` on every transition, so a report restored from
    the archive or promoted out of `potential` starts its clock the moment it becomes reapable.

    `last_activity_at` takes the newest of the timestamps the model already kept, and
    `last_human_touch_at` the newest person-attributed artefact or report action, each falling back
    to `created_at`. The human clock is the conservative direction: a report whose only evidence
    predates these tables reads as untouched since birth, which is what it is.
    """
    SignalReport = apps.get_model("signals", "SignalReport")
    SignalReportArtefact = apps.get_model("signals", "SignalReportArtefact")
    SignalReportAction = apps.get_model("signals", "SignalReportAction")
    SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")

    reapable = SignalReport._default_manager.filter(status__in=_REAPABLE)

    _batched_update(
        reapable.filter(last_activity_at__isnull=True),
        last_activity_at=Greatest("updated_at", Coalesce("last_run_at", "created_at"), "created_at"),
    )

    newest_human_artefact = Subquery(
        SignalReportArtefact._default_manager.filter(report_id=OuterRef("id"), created_by__isnull=False)
        .order_by("-created_at")
        .values("created_at")[:1],
        output_field=DateTimeField(),
    )
    newest_action = Subquery(
        # `all_teams`, not `objects`: this table is fail-closed per team and the backfill is
        # deliberately fleet-wide.
        SignalReportAction.all_teams.filter(report_id=OuterRef("id")).order_by("-last_at").values("last_at")[:1],
        output_field=DateTimeField(),
    )
    _batched_update(
        reapable.filter(last_human_touch_at__isnull=True),
        last_human_touch_at=Greatest(
            Coalesce(newest_human_artefact, F("created_at")),
            Coalesce(newest_action, F("created_at")),
        ),
    )

    # Every config row that exists right now belongs to a team that has been accumulating reports
    # since before the sweep existed, so none of them is opted in. Rows created after this runs
    # keep the null the column defaults to, which reads as enabled.
    _batched_update(
        SignalTeamConfig._default_manager.filter(stale_report_sweep_enabled__isnull=True),
        stale_report_sweep_enabled=False,
    )


class Migration(migrations.Migration):
    # Non-atomic so each batch commits and releases its row locks as it goes, rather than holding
    # every updated row locked until the whole backfill commits. Safe to resume after a partial
    # run: each pass only selects rows that are still unseeded.
    atomic = False

    dependencies = [
        ("signals", "0118_signalreport_staleness_indexes"),
    ]

    # Reverse is a noop: clearing the stamps would hand the sweep the null-reads-as-ancient
    # problem this backfill exists to close, and re-nulling the opt-out would opt every
    # established team back in.
    operations = [
        migrations.RunPython(backfill_staleness_clocks, migrations.RunPython.noop, elidable=True),
    ]
