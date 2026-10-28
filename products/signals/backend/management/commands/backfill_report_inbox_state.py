from argparse import ArgumentParser
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.implementation_pr_cache import repair_implementation_pr_cache
from products.signals.backend.scout_authorship import backfill_report_authoring_configs


class Command(BaseCommand):
    help = (
        "Fill the report columns the inbox filters on: the authoring scout config and the cached "
        "implementation PR flags. Safe to rerun."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, help="Limit to one team. Omitted means every team.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--only", choices=["authorship", "implementation-pr"], help="Run one of the two passes.")
        parser.add_argument("--after", help="Resume the selected pass after this id, as printed by an earlier run.")

    def handle(self, *args: object, **options: object) -> None:
        team_id = cast(int | None, options["team_id"])
        batch_size = max(1, min(cast(int, options["batch_size"]), 5000))
        only = cast(str | None, options["only"])
        after = cast(str | None, options["after"])
        if after and only is None:
            raise ValueError("--after needs --only, because each pass has its own cursor.")

        if only in (None, "authorship"):
            scanned = updated = 0
            for runs, reports, cursor in backfill_report_authoring_configs(
                team_id=team_id, batch_size=batch_size, after=after
            ):
                scanned += runs
                updated += reports
                self.stdout.write(
                    f"Authorship: scanned {scanned} runs, updated {updated} reports; resume after {cursor}"
                )

        if only in (None, "implementation-pr"):
            scanned = corrected = 0
            for batch in repair_implementation_pr_cache(team_id=team_id, batch_size=batch_size, after=after):
                scanned += batch.scanned
                corrected += batch.corrected
                self.stdout.write(
                    f"Implementation PR: scanned {scanned} reports, corrected {corrected}; resume after {batch.cursor}"
                )
