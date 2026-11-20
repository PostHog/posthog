from typing import Any

from django.core.management.base import BaseCommand

from products.logs.backend.destination_conversion import GroupOutcome, convert_team, outcome_counts


class Command(BaseCommand):
    help = (
        "Move the stock destinations of one team's platform-owned logs alerts off HogFunctions, onto "
        "destination rows. Reports only, unless --apply is given. Safe to run again."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The team to convert.")
        parser.add_argument("--apply", action="store_true", help="Write the changes. Without it, nothing is saved.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]
        apply = options["apply"]
        conversions = convert_team(team_id, apply=apply)
        for conversion in conversions:
            if conversion.outcome not in (GroupOutcome.CONVERTED, GroupOutcome.KEPT_ROW, GroupOutcome.REPLACED_ROW):
                hog_function_ids = ",".join(str(i) for i in conversion.hog_function_ids)
                detail = f" detail={conversion.detail!r}" if conversion.detail else ""
                self.stdout.write(
                    f"alert={conversion.alert_id} hog_functions={hog_function_ids} outcome={conversion.outcome}{detail}"
                )
        mode = "applied" if apply else "dry_run"
        self.stdout.write(f"team={team_id} {mode} {dict(outcome_counts(conversions)) or 'no HogFunction destinations'}")
