from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.alerts_platform.backend.facade.api import switch_off_legacy_rows
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.created_at_backfill_command import add_copy_backfill_arguments
from products.logs.backend.legacy_row_switch_off import switch_off_rows

SOURCE = SourceKind.LOGS


class Command(BaseCommand):
    help = (
        "Switch off the logs row of every logs alert the alerts platform owns, per team, in batches. "
        "The platform copy, which every reader shows, is not changed. Writes nothing without --apply."
    )

    def add_arguments(self, parser: Any) -> None:
        add_copy_backfill_arguments(parser)
        parser.add_argument("--batch-size", type=int, default=500, help="Rows per update.")

    def handle(self, *args: Any, **options: Any) -> None:
        run = switch_off_legacy_rows(
            source_kind=SOURCE,
            team_ids=options["team_ids"],
            switch_off=switch_off_rows,
            batch_size=options["batch_size"],
            apply=options["apply"],
        )
        for line in run.report(SOURCE, applied=options["apply"]):
            self.stdout.write(line)
        if run.failed_team_ids:
            raise CommandError(f"Failed for teams: {', '.join(map(str, run.failed_team_ids))}")
