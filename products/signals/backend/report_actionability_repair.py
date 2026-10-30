from collections.abc import Iterator
from uuid import UUID

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport


@frozen
class RepairedBatch:
    scanned: int
    corrected: int
    cursor: str


@frozen
class ReportIdBatch:
    rows: list[tuple[UUID, int]]
    cursor: str


def report_id_batches(*, team_id: int | None, batch_size: int, after: str | None = None) -> Iterator[ReportIdBatch]:
    """Walk report ids in id order, as (id, team id) rows, starting after report id `after`."""
    reports = SignalReport.objects.all()
    if team_id is not None:
        reports = reports.filter(team_id=team_id)
    reports = reports.order_by("id")
    while True:
        page = reports.filter(id__gt=after) if after else reports
        rows = list(page.values_list("id", "team_id")[:batch_size])
        if not rows:
            return
        after = str(rows[-1][0])
        yield ReportIdBatch(rows=rows, cursor=after)


def repair_latest_actionability(
    *, team_id: int | None, batch_size: int, after: str | None = None
) -> Iterator[RepairedBatch]:
    """Recompute `SignalReport.latest_actionability` and `latest_already_addressed` from the
    artefact log, one batch of reports at a time, starting after report id `after`.

    The receivers in receivers.py maintain both columns on every artefact write, so this is a
    repair for rows that drifted, not a routine job. Safe to rerun: each report is recomputed
    under its row lock and written only when it disagrees with its artefacts.
    """
    for batch in report_id_batches(team_id=team_id, batch_size=batch_size, after=after):
        corrected = sum(
            SignalReport.refresh_latest_actionability(team_id=row_team_id, report_id=report_id)
            for report_id, row_team_id in batch.rows
        )
        yield RepairedBatch(scanned=len(batch.rows), corrected=corrected, cursor=batch.cursor)
