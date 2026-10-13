from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from products.logs.backend.destination_hold_backs import held_back_destinations, unbound_destinations


class Command(BaseCommand):
    help = "List the logs alert destinations that cutover holds back, with the reasons."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Report one team only.")

    def handle(self, *args: Any, **options: Any) -> None:
        reasons: Counter[str] = Counter()
        for held in held_back_destinations(team_id=options["team_id"]):
            hold_backs = held.destination.hold_backs
            reasons.update(str(reason) for reason in hold_backs)
            self.stdout.write(
                f"team={held.team_id} alert={held.alert_id} destination={held.destination.hog_function_id} "
                f"template={held.destination.template_id} reasons={','.join(hold_backs)}"
            )
        for team_id, function_id in unbound_destinations(team_id=options["team_id"]):
            reasons["unbound"] += 1
            self.stdout.write(f"team={team_id} destination={function_id} reasons=unbound")
        self.stdout.write(f"Held back by reason: {dict(reasons) or 'none'}")
