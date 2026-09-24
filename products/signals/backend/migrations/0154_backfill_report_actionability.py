import json

from django.db import migrations

BATCH_SIZE = 500


def _latest_judgment(contents: list[str], max_actionability_length: int) -> tuple[str | None, bool | None] | None:
    """The newest parseable judgment of one report, newest content first.

    A row that is not a JSON object is skipped rather than ending the search, so one malformed
    artefact cannot hide the judgment written before it. Returns None when nothing parses. A
    judgment holds whatever string its author wrote, so a value too long for the column is
    dropped here rather than failing the whole deploy.
    """
    for content in contents:
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        actionability = parsed.get("actionability")
        already_addressed = parsed.get("already_addressed")
        if not isinstance(actionability, str) or len(actionability) > max_actionability_length:
            actionability = None
        return actionability, already_addressed if isinstance(already_addressed, bool) else None
    return None


def backfill_report_actionability(apps, schema_editor):
    """Fill the cached actionability of every report judged before the columns existed.

    The receivers write both columns on each judgment artefact write, so only reports whose
    newest judgment predates those receivers hold NULL. The inbox list now filters and sorts on
    the columns, so an unfilled report would drop out of the Reports tab it belongs in.

    The parsing is repeated here rather than taken from `report_actionability_repair`, which
    reads a report under its row lock through the live model. This runs against the historical
    models, and what an applied migration did must not change when the live parser changes.
    """
    SignalReport = apps.get_model("signals", "SignalReport")
    SignalReportArtefact = apps.get_model("signals", "SignalReportArtefact")
    max_actionability_length = SignalReport._meta.get_field("latest_actionability").max_length
    unfilled = SignalReport.objects.filter(
        latest_actionability__isnull=True, latest_already_addressed__isnull=True
    ).order_by("id")
    cursor = None
    while True:
        page = unfilled.filter(id__gt=cursor) if cursor else unfilled
        report_ids = list(page.values_list("id", flat=True)[:BATCH_SIZE])
        if not report_ids:
            return
        cursor = report_ids[-1]
        contents_by_report: dict[str, list[str]] = {}
        rows = (
            SignalReportArtefact.objects.filter(report_id__in=report_ids, type="actionability_judgment")
            .order_by("report_id", "-created_at")
            .values_list("report_id", "content")
        )
        for report_id, content in rows.iterator(chunk_size=1000):
            contents_by_report.setdefault(str(report_id), []).append(content)
        # Group the page by judgment value so a batch costs one UPDATE per distinct pair rather
        # than one per report.
        ids_by_value: dict[tuple[str | None, bool | None], list[str]] = {}
        for report_id, contents in contents_by_report.items():
            judgment = _latest_judgment(contents, max_actionability_length)
            if judgment is None or judgment == (None, None):
                continue
            ids_by_value.setdefault(judgment, []).append(report_id)
        for (actionability, already_addressed), ids in ids_by_value.items():
            # `update()`, not `save()`: filling a cache must not bump `updated_at`, which the
            # inbox sorts on. The UPDATE repeats the NULL conditions of the page query because a
            # receiver can store a newer judgment after the artefact read above. Postgres
            # re-checks the WHERE clause on the current row version, so that report is skipped.
            unfilled.filter(id__in=ids).update(
                latest_actionability=actionability, latest_already_addressed=already_addressed
            )


class Migration(migrations.Migration):
    # Non-atomic so each batch commits and releases its row locks as it goes, instead of holding
    # every report the backfill touches locked until the last batch commits. Safe to resume after
    # a partial run: a pass only selects reports that still hold no cached judgment, and the
    # values are recomputed from the artefact log rather than accumulated.
    atomic = False

    dependencies = [
        ("signals", "0153_signalreport_latest_actionability"),
    ]

    # Reverse is a noop: clearing the cache would hide judged reports from the inbox again.
    operations = [
        migrations.RunPython(backfill_report_actionability, migrations.RunPython.noop, elidable=True),
    ]
