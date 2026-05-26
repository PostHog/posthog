# ruff: noqa: T201
"""
Start a staff-initiated read-only audit run against a customer project.

Usage:
    python manage.py ph_audit \\
        --project-id 123 \\
        --skill auditing-experiments-flags \\
        --staff-email staff@posthog.com

The command mints a 1-hour, project-scoped, read-only Personal API key,
writes an `external_audit_started` entry to the project's activity log,
and prints status info. The actual agent dispatch (Temporal workflow that
runs the skill bundle against the project) is a planned follow-up — see
`dispatch_audit_run` in audit_command.py.

The raw ephemeral token is intentionally NOT printed: it has no consumer
yet, and surfacing it via stdout would leak it into shell history. When
the Temporal workflow is wired up, it will receive the token directly
from the return value of `dispatch_audit_run`.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.audit_command import AUDIT_SKILLS, AuditCommandError, dispatch_audit_run


class Command(BaseCommand):
    help = "Start a staff-initiated, read-only audit run against a customer project."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--project-id",
            type=int,
            required=True,
            help="Target project (team) ID.",
        )
        parser.add_argument(
            "--skill",
            type=str,
            required=True,
            help=f"Audit skill to run. One of: {', '.join(sorted(AUDIT_SKILLS))}.",
        )
        parser.add_argument(
            "--staff-email",
            type=str,
            required=True,
            help="Email of the PostHog staff user initiating the audit (must have is_staff=True).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        project_id: int = options["project_id"]
        skill: str = options["skill"]
        staff_email: str = options["staff_email"]

        try:
            staff_user = User.objects.get(email=staff_email)
        except User.DoesNotExist:
            raise CommandError(f"No PostHog user found for email '{staff_email}'.")

        team = Team.objects.select_related("organization").filter(pk=project_id).first()
        if team is None:
            raise CommandError(f"Project '{project_id}' not found.")

        try:
            result = dispatch_audit_run(team=team, staff_user=staff_user, skill=skill)
        except AuditCommandError as e:
            raise CommandError(str(e))

        org_name = team.organization.name if team.organization_id else "(unknown org)"
        expires_at = result.api_key.expires_at.isoformat() if result.api_key.expires_at else "(no expiry)"
        print(f"Started read-only `{skill}` audit on project '{team.name}' (org '{org_name}', id {team.id}).")
        print(f"Initiated by {staff_user.email}.")
        print(f"Ephemeral key id: {result.api_key.id} (expires {expires_at}).")
        print("Activity logged to project audit trail.")
