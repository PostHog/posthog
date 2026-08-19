import sys
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q
from django.utils import timezone as django_timezone

from posthog.models.user import User

from products.tasks.backend.models import CodeInvite, CodeInviteQuerySet

FILTER_OPTIONS = ("code", "created_before", "created_after", "created_by", "unredeemed")


class Command(BaseCommand):
    help = (
        "Expire PostHog Code invite codes by setting expires_at to now. "
        "Invites that are already expired are left unchanged. "
        "Pass at least one filter, or --all to expire every invite."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--all", action="store_true", help="Expire every invite. Cannot be combined with filters.")
        parser.add_argument("--code", nargs="+", metavar="CODE", help="Only these invite codes (case-insensitive)")
        parser.add_argument(
            "--created-before", metavar="DATETIME", help="Invites created before this ISO 8601 datetime (UTC if naive)"
        )
        parser.add_argument(
            "--created-after",
            metavar="DATETIME",
            help="Invites created at or after this ISO 8601 datetime (UTC if naive)",
        )
        parser.add_argument("--created-by", metavar="EMAIL", help="Invites created by the user with this email")
        parser.add_argument("--unredeemed", action="store_true", help="Only invites that were never redeemed")
        parser.add_argument("--dry-run", action="store_true", help="List matching invites without changing anything")
        parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")

    def handle(self, *args: Any, **options: Any) -> None:
        has_filters = any(options[name] for name in FILTER_OPTIONS)
        if options["all"] and has_filters:
            raise CommandError("--all cannot be combined with filters")
        if not options["all"] and not has_filters:
            raise CommandError(
                "Pass at least one filter (--code, --created-before, --created-after, --created-by, --unredeemed) or --all"
            )

        now = django_timezone.now()
        matched = self._apply_filters(CodeInvite.objects.all(), options)
        to_expire = list(matched.unexpired(now).order_by("created_at"))
        already_expired = matched.count() - len(to_expire)

        for invite in to_expire:
            limit = "unlimited" if invite.max_redemptions == 0 else str(invite.max_redemptions)
            expires = invite.expires_at.isoformat() if invite.expires_at else "never"
            self.stdout.write(
                f"{invite.code}  {invite.description or '-'}  redemptions {invite.redemption_count}/{limit}  "
                f"created {invite.created_at:%Y-%m-%d %H:%M}  expires {expires}"
            )
        self.stdout.write(f"{len(to_expire)} to expire, {already_expired} already expired (skipped)")

        if not to_expire:
            self.stdout.write(self.style.WARNING("No invites to expire."))
            return
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Dry run: {len(to_expire)} invite(s) would be expired."))
            return

        self._confirm(f"Expire {len(to_expire)} invite(s)? Type 'yes' to continue: ", yes=options["yes"])
        # Expire exactly the invites shown in the preview. Re-running the filter here would also
        # catch invites created during the confirmation prompt, expiring rows the operator never saw.
        count = CodeInvite.objects.filter(pk__in=[invite.pk for invite in to_expire]).expire(now)
        self.stdout.write(self.style.SUCCESS(f"Expired {count} invite(s)."))

    def _apply_filters(self, queryset: CodeInviteQuerySet, options: dict[str, Any]) -> CodeInviteQuerySet:
        if options["code"]:
            requested = {code.strip() for code in options["code"]}
            code_filter = Q()
            for code in requested:
                code_filter |= Q(code__iexact=code)
            queryset = queryset.filter(code_filter)
            found = {code.lower() for code in queryset.values_list("code", flat=True)}
            unknown = sorted(code for code in requested if code.lower() not in found)
            if unknown:
                raise CommandError(f"Unknown invite codes: {', '.join(unknown)}")
        before = (
            self._parse_datetime(options["created_before"], "--created-before") if options["created_before"] else None
        )
        after = self._parse_datetime(options["created_after"], "--created-after") if options["created_after"] else None
        if before and after and after >= before:
            raise CommandError("--created-after must be earlier than --created-before")
        if before:
            queryset = queryset.filter(created_at__lt=before)
        if after:
            queryset = queryset.filter(created_at__gte=after)
        if options["created_by"]:
            if not User.objects.filter(email__iexact=options["created_by"]).exists():
                raise CommandError(f"No user with email {options['created_by']!r}")
            queryset = queryset.filter(created_by__email__iexact=options["created_by"])
        if options["unredeemed"]:
            queryset = queryset.filter(redemption_count=0)
        return queryset

    @staticmethod
    def _parse_datetime(raw: str, flag: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise CommandError(f"{flag} is not a valid ISO 8601 datetime: {raw!r}")
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _confirm(prompt: str, *, yes: bool) -> None:
        if yes:
            return
        if not sys.stdin.isatty():
            raise CommandError("Refusing to expire invites non-interactively without --yes")
        if input(prompt).strip() != "yes":
            raise CommandError("Aborted.")
