from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.integrations import CrossTeamFilter, IntegrationManager

from products.workflows.backend.providers import SESProvider


class Command(BaseCommand):
    help = (
        "Delete an SES email identity that no longer has a matching email integration. "
        "Support remediation for domains orphaned in SES (e.g. the owning project or org "
        "was deleted before identity cleanup existed), which blocks any other organization "
        "from verifying the domain via the foreign-tenant guard."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("domain", type=str, help="The email domain whose SES identity should be deleted")

    def handle(self, *args: Any, **options: Any) -> None:
        domain = options["domain"].lower()
        in_use = IntegrationManager.email.any.list_across_teams(CrossTeamFilter(where={"domain": domain}))
        if in_use:
            team_ids = sorted(row.team_id for row in in_use)
            raise CommandError(
                f"Refusing to delete: domain {domain} is still used by email integration(s) on team(s) {team_ids}"
            )

        SESProvider().delete_identity(domain)
        self.stdout.write(self.style.SUCCESS(f"Deleted SES identity for {domain}"))
