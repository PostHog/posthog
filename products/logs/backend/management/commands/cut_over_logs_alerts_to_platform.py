from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.logs.backend.cutover_gate import CutoverRefused
from products.logs.backend.platform_cutover import cut_over_team


class Command(BaseCommand):
    help = "Hand one team's logs alerts to the alerts platform. Safe to run again."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The team to move.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]
        try:
            results = cut_over_team(team_id)
        except CutoverRefused as refused:
            for refusal in refused.refusals:
                self.stdout.write(
                    f"function={refusal.hog_function_id} alert={refusal.alert_id} "
                    f"bucket={refusal.bucket} refused={refusal.reason}"
                )
            raise CommandError(f"team={team_id} moved nothing: {len(refused.refusals)} destinations cannot move yet")
        for result in results:
            if result.skipped is not None:
                self.stdout.write(f"alert={result.alert_id} skipped={result.skipped}")
        outcomes = Counter(str(result.skipped or "moved") for result in results)
        self.stdout.write(f"team={team_id} {dict(outcomes) or 'no alerts'}")
