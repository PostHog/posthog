from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.facade.destinations import add_conversion_arguments, conversion_report
from products.logs.backend.destination_conversion import GroupOutcome, convert_team


class Command(BaseCommand):
    help = (
        "Move the stock destinations of one team's platform-owned logs alerts off HogFunctions, onto "
        "destination rows. Reports only, unless --apply is given. Safe to run again."
    )

    def add_arguments(self, parser: Any) -> None:
        add_conversion_arguments(parser)

    def handle(self, *args: Any, **options: Any) -> None:
        conversions = convert_team(options["team_id"], apply=options["apply"])
        for line in conversion_report(
            team_id=options["team_id"],
            apply=options["apply"],
            conversions=conversions,
            converted_outcomes=(GroupOutcome.CONVERTED, GroupOutcome.KEPT_ROW, GroupOutcome.REPLACED_ROW),
        ):
            self.stdout.write(line)
