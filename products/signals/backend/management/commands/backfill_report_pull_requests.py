from argparse import ArgumentParser
from collections.abc import Iterator
from typing import cast

from django.core.management.base import BaseCommand
from django.db import transaction

from products.signals.backend.models import SignalReport
from products.signals.backend.pull_requests import import_report_pull_requests


def backfill_report_pull_requests(*, team_id: int, after: str | None, batch_size: int) -> Iterator[tuple[int, str]]:
    while True:
        reports = SignalReport.objects.filter(team_id=team_id, assignment__isnull=False).order_by("id")
        if after:
            reports = reports.filter(id__gt=after)
        ids = list(reports.values_list("id", flat=True)[:batch_size])
        if not ids:
            return
        for report_id in ids:
            with transaction.atomic():
                report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
                import_report_pull_requests(report)
        after = str(ids[-1])
        yield len(ids), after


class Command(BaseCommand):
    help = "Import report ownership and assignment PR links into the work artefact log. Safe to rerun."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--after", help="Resume after this report UUID.")
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args: object, **options: object) -> None:
        for count, cursor in backfill_report_pull_requests(
            team_id=cast(int, options["team_id"]),
            after=cast(str | None, options["after"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 1000)),
        ):
            self.stdout.write(f"Imported {count} reports; resume with --after {cursor}")
