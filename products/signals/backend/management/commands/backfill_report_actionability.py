from argparse import ArgumentParser
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.facade.api import repair_report_actionability_cache


class Command(BaseCommand):
    help = "Recompute each report's cached actionability from its artefact log. Safe to rerun."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, help="Limit to one team. Omitted means every team.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--after", help="Resume after this report id, as printed by an earlier run.")

    def handle(self, *args: object, **options: object) -> None:
        scanned = fixed = 0
        for batch in repair_report_actionability_cache(
            team_id=cast(int | None, options["team_id"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
            after=cast(str | None, options["after"]),
        ):
            scanned += batch.scanned
            fixed += batch.corrected
            self.stdout.write(f"Scanned {scanned} reports, corrected {fixed}; resume after {batch.cursor}")
