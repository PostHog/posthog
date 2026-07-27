"""Hand-trigger one Signals agent run against a team + skill.

Used during dogfood to exercise the harness end-to-end without waiting for the
Temporal scheduler. Inserts a `SignalScoutRun` row, spawns a sandbox, polls until
the agent finishes, and prints the resulting run id and final message.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.scout_harness.runner import run_signals_scout
from products.signals.backend.scout_harness.skill_loader import SkillNotFoundError


class Command(BaseCommand):
    help = "Run one Signals scout against the given team using the given skill."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--skill-name", required=True)
        parser.add_argument("--skill-version", type=int, default=None)
        parser.add_argument(
            "--repository",
            default=None,
            help='GitHub repository for the sandbox (e.g. "posthog/posthog"). Optional.',
        )
        parser.add_argument("--verbose", action="store_true")

    def handle(self, *args, **options):
        try:
            result = run_signals_scout(
                team_id=options["team_id"],
                skill_name=options["skill_name"],
                skill_version=options["skill_version"],
                repository=options["repository"],
                verbose=options["verbose"],
            )
        except SkillNotFoundError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(f"Run {result.run_id} {result.status}"))
        self.stdout.write(f"  skill:    {result.skill_name} v{result.skill_version}")
        self.stdout.write(f"  runtime:  {result.runtime_s:.1f}s")
        if result.last_message:
            self.stdout.write("  message:")
            self.stdout.write(result.last_message)
