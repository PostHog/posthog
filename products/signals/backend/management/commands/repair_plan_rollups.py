from argparse import ArgumentParser
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.plan_rollup import repair_plans_behind_closed_steps


class Command(BaseCommand):
    help = "Complete the plans left open by steps that ended in closed. Safe to rerun."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, help="Limit to one team. Omitted means every team.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--after", help="Resume after this report id, as printed by an earlier run.")

    def handle(self, *args: object, **options: object) -> None:
        scanned = completed = 0
        for batch in repair_plans_behind_closed_steps(
            team_id=cast(int | None, options["team_id"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
            after=cast(str | None, options["after"]),
        ):
            scanned += batch.scanned
            completed += batch.corrected
            self.stdout.write(
                f"Scanned {scanned} closed steps, completed {completed} plans; resume after {batch.cursor}"
            )
