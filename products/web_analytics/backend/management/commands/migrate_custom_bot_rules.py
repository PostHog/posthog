from typing import Any

from django.core.management.base import BaseCommand

from products.web_analytics.backend.custom_bot_rules_migration import find_teams_with_flat_rules, migrate_team


class Command(BaseCommand):
    help = (
        "Rewrite pre-combiner flat custom bot rules stored on team.modifiers into the "
        "multi-condition shape. Dry run by default; pass --execute to apply."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--execute", action="store_true", help="Apply the rewrite. Without it, only report.")

    def handle(self, *args: Any, **options: Any) -> None:
        teams = find_teams_with_flat_rules()
        if not teams:
            self.stdout.write("No teams with flat custom bot rules found.")
            return

        total_rules = sum(team.flat_rules for team in teams)
        self.stdout.write(f"{len(teams)} team(s) with {total_rules} flat rule(s):")
        for team in teams:
            self.stdout.write(f"  team {team.team_id}: {team.flat_rules} flat rule(s)")

        if not options["execute"]:
            self.stdout.write("Dry run - nothing changed. Re-run with --execute to apply.")
            return

        migrated = sum(1 for team in teams if migrate_team(team.team_id))
        self.stdout.write(f"Migrated {migrated}/{len(teams)} team(s).")
