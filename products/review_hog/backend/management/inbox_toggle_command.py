"""Base class for the `enable_*` / `disable_*` inbox review management commands.

Each command names one toggle and one direction; this class carries the shared arguments, the
error mapping, and the output. It lives outside `commands/` so Django does not register it as a
command of its own.
"""

from typing import Any, ClassVar

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.review_hog.backend.inbox_review_toggles import (
    InboxToggleField,
    UsersNotInOrganization,
    apply_inbox_toggle,
    plan_inbox_toggle,
)


class InboxToggleCommand(BaseCommand):
    field: ClassVar[InboxToggleField]
    enabled: ClassVar[bool]

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="The team whose settings rows change. Without --user-ids, every active member of its organization.",
        )
        parser.add_argument(
            "--user-ids",
            type=int,
            nargs="+",
            metavar="USER_ID",
            help="Only change these users. Each must be a member of the team's organization.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without touching the database.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            plan = plan_inbox_toggle(
                team_id=options["team_id"],
                field=self.field,
                enabled=self.enabled,
                user_ids=options.get("user_ids"),
            )
        except (TeamScopeError, Team.DoesNotExist, UsersNotInOrganization) as err:
            raise CommandError(str(err)) from err

        changed = ", ".join(str(user_id) for user_id in plan.changed_user_ids) or "none"
        if options["dry_run"]:
            self.stdout.write(self.style.NOTICE(f"[dry-run] {plan.summary}. Nothing written."))
            self.stdout.write(f"Would change user id(s): {changed}")
            return

        apply_inbox_toggle(plan)
        self.stdout.write(self.style.SUCCESS(f"Done. {plan.summary}."))
        self.stdout.write(f"Changed user id(s): {changed}")
