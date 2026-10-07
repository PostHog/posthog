from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from ...logic.job import explain_team
from ...logic.rules import RULES
from ...logic.rules_diff import diff_candidates, override_rules


class Command(BaseCommand):
    help = "Show how a rules change would add, remove or re-rank a team's suggestion candidates."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team", type=int, required=True, help="Team id to compare.")
        parser.add_argument(
            "--set",
            action="append",
            required=True,
            dest="assignments",
            help="A rule to change, as section.field=value, for example materialize.min_seconds_saved=300.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        today = timezone.now().date()
        proposed = override_rules(RULES, options["assignments"])
        _, before = explain_team(options["team"], today=today, rules=RULES)
        _, after = explain_team(options["team"], today=today, rules=proposed)
        for kind, diff in diff_candidates(before, after).items():
            self.stdout.write(f"{kind}: +{len(diff.added)} -{len(diff.removed)} ~{len(diff.reranked)}")
            for label, names in (("added", diff.added), ("removed", diff.removed), ("re-ranked", diff.reranked)):
                for name in names:
                    self.stdout.write(f"  {label}: {name}")
