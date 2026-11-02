"""Local dev tool: seed the Signals inbox with a spread of realistic reports + task runs.

Drops several fully-formed `SignalReport`s into the inbox so the UI has something to look at.
The seeding lives in `products/signals/backend/inbox_seed.py`, which the Hedgebox demo matrix also
calls for new local demo projects.

Runs are recorded via the production dual-write (`record_implementation_task`), so seeded reports are
billable-faithful; for the refund-path matrix (excluded/credited/exempt) use `seed_refund_test_data`.

`--github-optional` seeds the shape GitHub-optional research leaves when the project has no GitHub
integration: a `data_only` repo selection with no repository, no commits, no GitHub reviewers, and
no implementation runs, since opening a pull request still needs GitHub access.

DEBUG only.

    python manage.py seed_inbox_data --team-id 1
    python manage.py seed_inbox_data --team-id 1 --count 12 --clear
    python manage.py seed_inbox_data --team-id 1 --no-runs
    python manage.py seed_inbox_data --team-id 1 --github-optional
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import OrganizationMembership, Team

from products.signals.backend.inbox_seed import NoSeedFixturesError, seed_demo_inbox


class Command(BaseCommand):
    help = "Seed the Signals inbox with realistic reports and task runs (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed reports for")
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="User to attribute tasks to (default: first member of the team's organization)",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=None,
            help="How many reports to create (default: one per fixture; cycles fixtures when larger)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete the team's existing signal reports (and their artefacts) before seeding",
        )
        parser.add_argument(
            "--no-runs",
            dest="with_runs",
            action="store_false",
            help="Skip creating task runs + logs (reports and artefacts only)",
        )
        parser.add_argument(
            "--github-optional",
            action="store_true",
            help="Seed data-only reports researched without a GitHub integration (no repository, commits, or runs)",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        team = self._get_team(options["team_id"])
        try:
            seeded = seed_demo_inbox(
                team_id=team.id,
                user_id=self._resolve_user_id(team, options["user_id"]),
                count=options["count"],
                with_runs=options["with_runs"],
                github_optional=options["github_optional"],
                clear=options["clear"],
                log=self.stdout.write,
            )
        except NoSeedFixturesError as e:
            raise CommandError(str(e))

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(seeded.report_ids)} report(s) for team {team.id} ({team.name}).")
        )

    def _get_team(self, team_id: int) -> Team:
        try:
            return Team.objects.select_related("organization").get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")

    def _resolve_user_id(self, team: Team, user_id: int | None) -> int:
        if user_id is not None:
            return user_id
        membership = (
            OrganizationMembership.objects.filter(organization_id=team.organization_id)
            .order_by("joined_at")
            .values_list("user_id", flat=True)
            .first()
        )
        if membership is None:
            raise CommandError(f"Team {team.id}'s organization has no members; pass --user-id explicitly")
        return membership
