from argparse import ArgumentParser
from collections.abc import Iterator
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.suggested_reviewer_index import sync_suggested_reviewer_index


def backfill_suggested_reviewer_index(*, team_id: int, after: str | None, batch_size: int) -> Iterator[tuple[int, str]]:
    while True:
        artefacts = SignalReportArtefact.objects.filter(
            team_id=team_id, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
        ).order_by("report_id")
        if after:
            artefacts = artefacts.filter(report_id__gt=after)
        report_ids = list(artefacts.values_list("report_id", flat=True).distinct()[:batch_size])
        if not report_ids:
            return
        for report_id in report_ids:
            sync_suggested_reviewer_index(team_id=team_id, report_id=str(report_id))
        after = str(report_ids[-1])
        yield len(report_ids), after


class Command(BaseCommand):
    help = (
        "Rebuild the indexed suggested-reviewer rows from the reviewer artefact log, for every "
        "report in a project that has one. Each report is rewritten from its current artefact, so "
        "this both backfills reports written before the index existed and repairs a report whose "
        "rows drifted. Safe to rerun."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--after", help="Resume after this report UUID.")
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args: object, **options: object) -> None:
        for count, cursor in backfill_suggested_reviewer_index(
            team_id=cast(int, options["team_id"]),
            after=cast(str | None, options["after"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 1000)),
        ):
            self.stdout.write(f"Rebuilt {count} reports; resume with --after {cursor}")
