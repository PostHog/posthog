from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from posthog.models import OrganizationMembership, Team, User
from posthog.models.team.extensions import get_or_create_team_extension

from products.signals.backend.models import SignalAutonomyConfig


class Command(BaseCommand):
    help = (
        "Enable Signals autonomy for a team by setting the minimum autostart priority "
        "and replacing the opted-in autonomy users from a comma-separated list of emails."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "team_id",
            type=int,
            help="Team ID to update",
        )
        parser.add_argument(
            "priority_threshold",
            type=str,
            choices=[choice for choice, _label in SignalAutonomyConfig.Priority.choices],
            help="Minimum autostart priority threshold (P0-P4)",
        )
        parser.add_argument(
            "emails",
            type=str,
            help="Comma-separated list of opted-in user email addresses",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        priority_threshold = options["priority_threshold"]
        raw_emails = options["emails"]

        try:
            team = Team.objects.select_related("organization").get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")

        emails = self._parse_emails(raw_emails)
        if not emails:
            raise CommandError("At least one email address must be provided")

        resolved_users = self._resolve_users_for_team(team, emails)

        autonomy_config = get_or_create_team_extension(team, SignalAutonomyConfig)
        autonomy_config.minimum_autostart_priority = priority_threshold
        autonomy_config.opted_in_user_ids = [user.id for user in resolved_users]
        autonomy_config.save(update_fields=["minimum_autostart_priority", "opted_in_user_ids"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated Signals autonomy for team {team.id} ({team.name})\n"
                f"  priority_threshold: {autonomy_config.minimum_autostart_priority}\n"
                f"  opted_in_user_ids: {autonomy_config.opted_in_user_ids}"
            )
        )

        for user in resolved_users:
            self.stdout.write(f"  - {user.id}: {user.email}")

        self.stdout.write("")
        if not team.organization.is_ai_data_processing_approved:
            self.stdout.write(
                self.style.WARNING(
                    "AI data processing is not approved for this organization. emit_signal() will no-op until that is enabled."
                )
            )

        self.stdout.write(
            self.style.WARNING(
                "Make sure the team has an enabled SignalSourceConfig for error_tracking / issue_spiking before ingesting the test signal."
            )
        )

    def _parse_emails(self, raw_emails: str) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for email in raw_emails.split(","):
            cleaned = email.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            normalized.append(cleaned)
            seen.add(cleaned)

        return normalized

    def _resolve_users_for_team(self, team: Team, emails: list[str]) -> list[User]:
        email_query = Q()
        for email in emails:
            email_query |= Q(user__email__iexact=email)

        memberships = list(
            OrganizationMembership.objects.filter(
                organization_id=team.organization_id,
            )
            .filter(email_query)
            .select_related("user")
            .order_by("user_id")
        )

        users_by_email = {membership.user.email.lower(): membership.user for membership in memberships}
        missing_emails = [email for email in emails if email not in users_by_email]

        if missing_emails:
            raise CommandError(
                "These emails do not belong to users in the team's organization: " + ", ".join(missing_emails)
            )

        return [users_by_email[email] for email in emails]
