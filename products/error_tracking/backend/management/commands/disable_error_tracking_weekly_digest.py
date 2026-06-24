"""Disable error tracking weekly digest for specific users.

Admin tool to manually disable the error tracking weekly digest for users,
identified by email or organization membership.

Usage:
    # Dry-run for specific user
    python manage.py disable_error_tracking_weekly_digest --email user@example.com --dry-run

    # Disable for multiple users
    python manage.py disable_error_tracking_weekly_digest --email user1@example.com --email user2@example.com

    # Disable for all users in an organization (per-project, scoped to the org's teams only)
    python manage.py disable_error_tracking_weekly_digest --organization-id 12345

    # Combine email and org filters (union). Users matched by --organization-id are always
    # disabled per-project for that org's teams, even if also matched via --email.
    python manage.py disable_error_tracking_weekly_digest --email user@example.com --organization-id 12345
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.models import Team
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

PROJECT_SETTING_KEY = "error_tracking_weekly_digest_project_enabled"
GLOBAL_SETTING_KEY = "error_tracking_weekly_digest"


class Command(BaseCommand):
    help = "Disable error tracking weekly digest for users by email or organization membership."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            action="append",
            default=[],
            help="User email to disable digest for (repeatable). Disables globally for the user.",
        )
        parser.add_argument(
            "--organization-id",
            type=str,
            default=None,
            help="Disable digest for all users in this organization (UUID). Scoped to the org's projects only.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which users would be updated without writing changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        emails: list[str] = options["email"]
        organization_id: str | None = options["organization_id"]
        dry_run: bool = options["dry_run"]

        if not emails and not organization_id:
            self.stderr.write(self.style.ERROR("Must provide at least one --email or --organization-id."))
            return

        org_user_ids: set[int] = set()
        if organization_id is not None:
            org_user_ids = set(
                OrganizationMembership.objects.filter(organization_id=organization_id).values_list("user_id", flat=True)
            )

        email_user_ids: set[int] = set()
        if emails:
            email_user_ids = set(User.objects.filter(email__in=emails).values_list("id", flat=True))

        email_only_user_ids = email_user_ids - org_user_ids

        total_matched = len(org_user_ids) + len(email_only_user_ids)
        if total_matched == 0:
            self.stdout.write(self.style.WARNING("No matching users found."))
            return

        self.stdout.write(f"Found {total_matched} user(s) matching criteria.")

        org_team_ids: list[int] = []
        if org_user_ids:
            org_team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))

        updated_count = 0
        skipped_count = 0

        for user in User.objects.filter(id__in=org_user_ids).order_by("email"):
            if self._disable_for_org_teams(user, org_team_ids, dry_run=dry_run):
                updated_count += 1
            else:
                skipped_count += 1

        for user in User.objects.filter(id__in=email_only_user_ids).order_by("email"):
            if self._disable_globally(user, dry_run=dry_run):
                updated_count += 1
            else:
                skipped_count += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"Dry run — would update {updated_count} user(s), {skipped_count} already disabled.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Done. Updated {updated_count} user(s), {skipped_count} already disabled.")
            )

    def _disable_for_org_teams(self, user: User, org_team_ids: list[int], *, dry_run: bool) -> bool:
        if not org_team_ids:
            self.stdout.write(f"  Skipping {user.email} — organization has no projects.")
            return False

        current_settings = user.partial_notification_settings or {}
        project_map = current_settings.get(PROJECT_SETTING_KEY) or {}

        if not self._needs_org_update(project_map, org_team_ids):
            self.stdout.write(f"  Skipping {user.email} — already disabled for org's projects.")
            return False

        if dry_run:
            self.stdout.write(f"  Would disable {len(org_team_ids)} org project(s) for {user.email}")
            return True

        with transaction.atomic():
            user_obj = User.objects.select_for_update().get(pk=user.pk)
            current_settings = user_obj.partial_notification_settings or {}
            project_map = dict(current_settings.get(PROJECT_SETTING_KEY) or {})
            if not self._needs_org_update(project_map, org_team_ids):
                self.stdout.write(f"  Skipping {user.email} — already disabled for org's projects.")
                return False
            for tid in org_team_ids:
                project_map[str(tid)] = False
            current_settings[PROJECT_SETTING_KEY] = project_map
            user_obj.partial_notification_settings = current_settings
            user_obj.save(update_fields=["partial_notification_settings"])

        self.stdout.write(f"  Disabled {len(org_team_ids)} org project(s) for {user.email}")
        return True

    def _disable_globally(self, user: User, *, dry_run: bool) -> bool:
        current_settings = user.partial_notification_settings or {}
        if current_settings.get(GLOBAL_SETTING_KEY) is False:
            self.stdout.write(f"  Skipping {user.email} — already disabled.")
            return False

        if dry_run:
            self.stdout.write(f"  Would disable for {user.email}")
            return True

        with transaction.atomic():
            user_obj = User.objects.select_for_update().get(pk=user.pk)
            current_settings = user_obj.partial_notification_settings or {}
            if current_settings.get(GLOBAL_SETTING_KEY) is False:
                self.stdout.write(f"  Skipping {user.email} — already disabled.")
                return False
            current_settings[GLOBAL_SETTING_KEY] = False
            user_obj.partial_notification_settings = current_settings
            user_obj.save(update_fields=["partial_notification_settings"])

        self.stdout.write(f"  Disabled for {user.email}")
        return True

    @staticmethod
    def _needs_org_update(project_map: dict, org_team_ids: list[int]) -> bool:
        return any(project_map.get(str(tid)) is not False for tid in org_team_ids)
