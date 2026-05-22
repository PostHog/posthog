"""Disable error tracking weekly digest for specific users.

Admin tool to manually disable the error tracking weekly digest for users,
identified by email or organization membership.

Usage:
    # Dry-run for specific user
    python manage.py disable_error_tracking_weekly_digest --email user@example.com --dry-run

    # Disable for multiple users
    python manage.py disable_error_tracking_weekly_digest --email user1@example.com --email user2@example.com

    # Disable for all users in an organization
    python manage.py disable_error_tracking_weekly_digest --organization-id 12345

    # Combine email and org filters (union)
    python manage.py disable_error_tracking_weekly_digest --email user@example.com --organization-id 12345
"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from posthog.models.user import User


class Command(BaseCommand):
    help = "Disable error tracking weekly digest for users by email or organization membership."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--email",
            action="append",
            default=[],
            help="User email to disable digest for (repeatable).",
        )
        parser.add_argument(
            "--organization-id",
            type=int,
            default=None,
            help="Disable digest for all users in this organization.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which users would be updated without writing changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        emails: list[str] = options["email"]
        organization_id: int | None = options["organization_id"]
        dry_run: bool = options["dry_run"]

        if not emails and not organization_id:
            self.stderr.write(self.style.ERROR("Must provide at least one --email or --organization-id."))
            return

        users = self._get_users(emails=emails, organization_id=organization_id)

        if not users:
            self.stdout.write(self.style.WARNING("No matching users found."))
            return

        self.stdout.write(f"Found {len(users)} user(s) matching criteria.")

        updated_count = 0
        skipped_count = 0

        for user in users:
            current_settings = user.partial_notification_settings or {}
            if current_settings.get("error_tracking_weekly_digest") is False:
                self.stdout.write(f"  Skipping {user.email} — already disabled.")
                skipped_count += 1
                continue

            if dry_run:
                self.stdout.write(f"  Would disable for {user.email}")
            else:
                current_settings["error_tracking_weekly_digest"] = False
                User.objects.filter(pk=user.pk).update(partial_notification_settings=current_settings)
                self.stdout.write(f"  Disabled for {user.email}")

            updated_count += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"Dry run — would update {updated_count} user(s), {skipped_count} already disabled.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Done. Updated {updated_count} user(s), {skipped_count} already disabled.")
            )

    def _get_users(self, *, emails: list[str], organization_id: int | None) -> list[User]:
        user_ids: set[int] = set()

        if emails:
            email_users = User.objects.filter(email__in=emails).values_list("id", flat=True)
            user_ids.update(email_users)

        if organization_id is not None:
            from posthog.models.organization import OrganizationMembership

            org_user_ids = OrganizationMembership.objects.filter(organization_id=organization_id).values_list(
                "user_id", flat=True
            )
            user_ids.update(org_user_ids)

        if not user_ids:
            return []

        return list(User.objects.filter(id__in=user_ids).order_by("email"))
