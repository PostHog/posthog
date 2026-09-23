from argparse import ArgumentParser
from collections.abc import Iterator
from typing import cast

from django.core.management.base import BaseCommand

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalReportArtefact


@frozen
class RepairedBatch:
    scanned: int
    corrected: int
    cursor: str


def backfill_report_actionability(
    *, team_id: int | None, batch_size: int, after: str | None = None
) -> Iterator[RepairedBatch]:
    """Recompute `SignalReport.latest_actionability` and `latest_already_addressed` from the
    artefact log, one batch of reports at a time, starting after report id `after`.

    The receivers in receivers.py maintain both columns on every artefact write, so this is a
    repair for rows that drifted, not a routine job. Safe to rerun: it writes only the reports
    that disagree with their artefacts.
    """
    reports = SignalReport.objects.all()
    if team_id is not None:
        reports = reports.filter(team_id=team_id)
    reports = reports.order_by("id")
    while True:
        page = reports.filter(id__gt=after) if after else reports
        rows = list(page.values_list("id", "latest_actionability", "latest_already_addressed")[:batch_size])
        if not rows:
            return
        after = str(rows[-1][0])
        corrected = 0
        for report_id, actionability, already_addressed in rows:
            current = SignalReportArtefact.latest_actionability(report_id)
            if current.actionability == actionability and current.already_addressed == already_addressed:
                continue
            # Compare-and-set on the values read above, so a receiver that wrote a newer judgment
            # between the read and this write is not overwritten with the older recomputation.
            corrected += SignalReport.objects.filter(
                id=report_id, latest_actionability=actionability, latest_already_addressed=already_addressed
            ).update(latest_actionability=current.actionability, latest_already_addressed=current.already_addressed)
        yield RepairedBatch(scanned=len(rows), corrected=corrected, cursor=after)


class Command(BaseCommand):
    help = "Recompute each report's cached actionability from its artefact log. Safe to rerun."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, help="Limit to one team. Omitted means every team.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--after", help="Resume after this report id, as printed by an earlier run.")

    def handle(self, *args: object, **options: object) -> None:
        scanned = fixed = 0
        for batch in backfill_report_actionability(
            team_id=cast(int | None, options["team_id"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
            after=cast(str | None, options["after"]),
        ):
            scanned += batch.scanned
            fixed += batch.corrected
            self.stdout.write(f"Scanned {scanned} reports, corrected {fixed}; resume after {batch.cursor}")
