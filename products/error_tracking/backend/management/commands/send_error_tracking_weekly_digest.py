"""Send an error tracking weekly digest email to an arbitrary recipient, for testing.

Builds the full digest for an organization (every project with exceptions this week,
no per-user notification filtering) and delivers it through the digest workflow webhook.

Usage:
    # Recipient is a PostHog user in exactly one org
    python manage.py send_error_tracking_weekly_digest --email user@example.com

    # Explicit org (required when the recipient isn't a user or belongs to multiple orgs)
    python manage.py send_error_tracking_weekly_digest --email anyone@example.com --org-id <uuid>
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.models.organization import Organization
from posthog.models.user import User

from products.error_tracking.backend import weekly_digest


class Command(BaseCommand):
    help = "Send an error tracking weekly digest email to any address via the digest workflow (testing tool)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", type=str, required=True, help="Recipient email address.")
        parser.add_argument(
            "--org-id",
            type=str,
            default=None,
            help="Organization (UUID) to build the digest for. Defaults to the recipient's org when they are a user.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email: str = options["email"]

        if not weekly_digest.get_digest_workflow_webhook_url():
            raise CommandError("No digest delivery workflow for this region (CLOUD_DEPLOYMENT)")

        user = User.objects.filter(email=email).first()
        org = self._resolve_org(options["org_id"], user, email)

        teams = list(Team.objects.filter(organization_id=org.id))
        if not teams:
            raise CommandError(f"Organization {org.id} has no projects")

        team_ids_with_exceptions = {row[0] for row in weekly_digest.get_exception_counts([t.id for t in teams])}
        sections = []
        for team in teams:
            if team.id not in team_ids_with_exceptions:
                continue
            data = weekly_digest.build_team_digest_data(team)
            if data:
                sections.append(data)

        if not sections:
            raise CommandError(f"No exceptions in the last 7 days for organization {org.id}, nothing to send")

        sections.sort(key=lambda d: d["exception_count"], reverse=True)

        distinct_id = user.distinct_id if user else email
        digest = {
            "recipient_email": email,
            "org_name": org.name,
            "project_sections": [weekly_digest.build_team_section_payload(d) for d in sections],
            "disabled_project_names": [],
            "excluded_project_count": len(teams) - len(sections),
            "settings_url": f"{settings.SITE_URL}/settings/user-notifications?highlight=et-weekly-digest",
            "feedback_survey_url": f"https://us.posthog.com/external_surveys/019c7fd6-7cfa-0000-2b03-a8e5d4c03743?distinct_id={distinct_id}",
        }

        weekly_digest.send_digest_to_workflow(digest, distinct_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent weekly digest for org '{org.name}' ({org.id}) to {email} ({len(sections)} project sections)"
            )
        )

    def _resolve_org(self, org_id: str | None, user: User | None, email: str) -> Organization:
        if org_id:
            try:
                return Organization.objects.get(id=org_id)
            except Organization.DoesNotExist:
                raise CommandError(f"Organization {org_id} not found")

        if not user:
            raise CommandError(f"No user with email {email} - pass --org-id to pick the digest organization")

        orgs = list(user.organizations.all())
        if not orgs:
            raise CommandError(f"User {email} belongs to no organizations - pass --org-id")
        if len(orgs) > 1:
            org_list = ", ".join(f"{o.name} ({o.id})" for o in orgs)
            raise CommandError(f"User {email} belongs to multiple organizations, pass --org-id. Options: {org_list}")
        return orgs[0]
