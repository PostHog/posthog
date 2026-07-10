from django.core.management.base import BaseCommand, CommandError

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    clear_team_oom_pin,
    list_oom_pinned_team_ids,
)


class Command(BaseCommand):
    help = (
        "List or clear web-analytics precompute OOM pins. A pinned team's precompute "
        "inserts are capped to 1-day windows (set reactively after a MEMORY_LIMIT_EXCEEDED "
        "insert, self-expiring in 14 days). Clear a pin when the underlying pressure is "
        "gone, e.g. after a cluster upscale or a stored-row cap reduction, so the team's "
        "inserts run at full band width again."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--team-id", type=int, help="Clear the pin for this team only")
        group.add_argument("--all", action="store_true", help="Clear every pin (requires --yes)")
        group.add_argument("--list", action="store_true", help="List pinned teams without clearing")
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirm the global --all clear; without it the command only prints what it would remove",
        )

    def handle(self, *args, **options):
        if options["list"]:
            pinned = list_oom_pinned_team_ids()
            if not pinned:
                self.stdout.write("No teams are OOM-pinned.")
            for team_id in pinned:
                self.stdout.write(f"pinned: team {team_id}")
            return

        if options["team_id"] is not None:
            if clear_team_oom_pin(options["team_id"]):
                self.stdout.write(self.style.SUCCESS(f"Cleared OOM pin for team {options['team_id']}"))
            else:
                self.stdout.write(f"Team {options['team_id']} was not pinned.")
            return

        pinned = list_oom_pinned_team_ids()
        if not options["yes"]:
            # Pins exist because those teams recently OOMed a full-width insert; a global
            # clear re-exposes all of them at once, so it needs explicit confirmation.
            teams = ", ".join(str(t) for t in pinned) or "none"
            raise CommandError(
                f"--all would clear {len(pinned)} pin(s) (teams: {teams}). Re-run with --yes to confirm."
            )
        for team_id in pinned:
            clear_team_oom_pin(team_id)
        self.stdout.write(self.style.SUCCESS(f"Cleared {len(pinned)} OOM pin(s)."))
