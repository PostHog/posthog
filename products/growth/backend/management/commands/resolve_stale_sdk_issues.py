from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.sdk_version_rollup import sdk_versions_window
from products.growth.backend.stale_sdk_issues import find_stale_sdk_issues, resolve_sdk_issues_for_teams


class Command(BaseCommand):
    help = (
        "Resolve active sdk_outdated issues for teams with no SDK traffic in the rollup window or no member "
        "login in the check's activity window. Sends no alerts. Dry run unless --commit."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--commit", action="store_true", help="Resolve the issues. Without it, only report.")

    def handle(self, *args: object, **options: object) -> None:
        window = sdk_versions_window()
        if window is None:
            raise CommandError("The SDK versions rollup has no fresh window, so SDK traffic cannot be judged.")

        stale = find_stale_sdk_issues(window)
        self.stdout.write(
            f"Window {window.start} to {window.end}: {stale.active_issues} active issues, "
            f"{len(stale.no_sdk_traffic_team_ids)} teams with no SDK traffic, "
            f"{len(stale.no_recent_login_team_ids)} teams with no recent login, "
            f"{len(stale.team_ids)} teams to resolve."
        )
        if not options["commit"]:
            self.stdout.write("Dry run. Pass --commit to resolve these issues.")
            return

        resolved = resolve_sdk_issues_for_teams(stale.team_ids)
        self.stdout.write(f"Resolved {resolved} issues.")
