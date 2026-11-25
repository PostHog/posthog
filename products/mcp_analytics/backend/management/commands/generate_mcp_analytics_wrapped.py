"""Compute one project's MCP Wrapped, to check the numbers before anything is scheduled."""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from posthog.models.team.team import Team

from products.mcp_analytics.backend.wrapped.generate import compute_wrapped, generate_wrapped_snapshot


class Command(BaseCommand):
    help = "Compute MCP Wrapped for one project and store it as that year's snapshot, or print it with --dry-run."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Project (team) ID to compute the wrap for.")
        parser.add_argument("--year", type=int, default=None, help="Year to cover. Defaults to the current year.")
        parser.add_argument("--dry-run", action="store_true", help="Print the payload and store nothing.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        year: int = options["year"] or timezone.now().year
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} does not exist.")

        if options["dry_run"]:
            generation = compute_wrapped(team, year)
            self.stdout.write(json.dumps({"status": generation.status, "payload": generation.payload}, indent=2))
            return

        snapshot = generate_wrapped_snapshot(team, year)
        self.stdout.write(self.style.SUCCESS(f"Stored the {year} snapshot for team {team_id}: {snapshot.status}."))
