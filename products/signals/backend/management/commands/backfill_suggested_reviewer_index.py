from argparse import ArgumentParser
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.suggested_reviewer_index import rebuild_suggested_reviewer_index_for_team


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
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Skip reports that already have rows, instead of rewriting them.",
        )

    def handle(self, *args: object, **options: object) -> None:
        for count, cursor in rebuild_suggested_reviewer_index_for_team(
            team_id=cast(int, options["team_id"]),
            after=cast(str | None, options["after"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 1000)),
            only_missing=cast(bool, options["only_missing"]),
        ):
            self.stdout.write(f"Rebuilt {count} reports; resume with --after {cursor}")
