from django.core.management.base import BaseCommand

import structlog

from products.tasks.backend.models import CodeInvite

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Deactivate PostHog Code invite codes so they can no longer be redeemed. "
        "By default only unused (never-redeemed) codes are expired; pass --all to expire every active code."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Expire every active code, including ones that have already been redeemed at least once. "
            "Use this to stop all further redemptions immediately.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many codes would be expired without changing anything.",
        )

    def handle(self, *args, **options):
        expire_all = options["all"]
        dry_run = options["dry_run"]

        # is_redeemable checks is_active first, so flipping it to False is enough to block redemption
        # while preserving the codes and their redemption audit trail.
        codes = CodeInvite.objects.filter(is_active=True)
        if not expire_all:
            codes = codes.filter(redemption_count=0)

        scope = "all active" if expire_all else "unused (never redeemed)"
        count = codes.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: would expire {count} {scope} invite code(s)"))
            return

        if count == 0:
            self.stdout.write(self.style.SUCCESS(f"No {scope} invite codes to expire"))
            return

        updated = codes.update(is_active=False)

        logger.info("code_invites_expired", expired_count=updated, expire_all=expire_all)
        self.stdout.write(self.style.SUCCESS(f"Expired {updated} {scope} invite code(s)"))
