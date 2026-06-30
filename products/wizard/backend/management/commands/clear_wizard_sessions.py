"""Clear wizard session rows from the database.

Usage:
    python manage.py clear_wizard_sessions --team 123
    python manage.py clear_wizard_sessions --user user@example.com
    python manage.py clear_wizard_sessions --user 42 --workflow posthog-integration
    python manage.py clear_wizard_sessions --session-id onboarding-nextjs-2026-05-19T10:00:00Z --team 123
    python manage.py clear_wizard_sessions --user user@example.com --dry-run

`--user` resolves to every team in every organization the user is a member of.
The command refuses to run with no scoping flag.

`--all` clears every WizardSession row in the database and is intended for
dev/test environments only. In production, `--all` requires the operator to
also pass `--yes-i-really-mean-it-in-prod` so a fat-fingered command can't
wipe the table by accident.

`--session-id` requires a team scope (`--team` or `--user`) because session_id
is only unique per team — without one, the same id can match rows in multiple
tenants.
"""

import sys
from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from posthog.cloud_utils import is_cloud
from posthog.models.team import Team
from posthog.models.user import User

from products.wizard.backend.models import WizardSession


class Command(BaseCommand):
    help = "Clear wizard session rows for a team, user, or specific session_id."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--user",
            type=str,
            help="User email or numeric ID. Resolves to every team in every org the user belongs to.",
        )
        parser.add_argument("--team", type=int, help="Team (project) ID.")
        parser.add_argument("--workflow", type=str, help="Filter by workflow_id (e.g. posthog-integration).")
        parser.add_argument("--skill", type=str, help="Filter by skill_id.")
        parser.add_argument("--session-id", type=str, help="Delete a single session by session_id.")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Required to wipe every wizard session row. Refused in prod unless --yes-i-really-mean-it-in-prod is also passed.",
        )
        parser.add_argument(
            "--yes-i-really-mean-it-in-prod",
            action="store_true",
            help="Required alongside --all when running against PostHog Cloud / DEBUG=False.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be deleted without touching the database.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        user_arg: str | None = opts.get("user")
        team_id: int | None = opts.get("team")
        workflow_id: str | None = opts.get("workflow")
        skill_id: str | None = opts.get("skill")
        session_id: str | None = opts.get("session_id")
        clear_all: bool = opts.get("all", False)
        prod_confirm: bool = opts.get("yes_i_really_mean_it_in_prod", False)
        dry_run: bool = opts.get("dry_run", False)

        if not any([user_arg, team_id, session_id, clear_all]):
            raise CommandError(
                "Provide at least one of --user, --team, --session-id, or --all. "
                "Refusing to clear the entire wizard_sessions table by accident."
            )

        # session_id is only unique per team — without a team scope the same id
        # can match rows in multiple tenants. Require an explicit tenant scope
        # so an operator can't quietly cross tenant boundaries by typing the
        # wrong flag.
        if session_id and not (team_id or user_arg or clear_all):
            raise CommandError(
                "--session-id requires --team (or --user, or --all if you really "
                "intend to delete that session id across every tenant). session_id "
                "is unique per team, not globally."
            )

        # Prod guard for --all: PostHog Cloud and any non-DEBUG instance refuse
        # to wipe the table without an explicit acknowledgement.
        if clear_all and not dry_run:
            if is_cloud() or not settings.DEBUG:
                if not prod_confirm:
                    raise CommandError(
                        "--all on a non-DEBUG / cloud instance requires "
                        "--yes-i-really-mean-it-in-prod. Re-run with that flag if "
                        "you really intend to delete every wizard session row."
                    )
            # Interactive confirmation when stdin is a TTY (scripted runs already
            # opted-in via the prod confirm flag).
            if sys.stdin.isatty():
                answer = input("Type 'delete all wizard sessions' to proceed: ")
                if answer.strip() != "delete all wizard sessions":
                    raise CommandError("Confirmation phrase didn't match — aborting.")

        qs: QuerySet[WizardSession] = WizardSession.objects.unscoped().all()

        team_ids: list[int] = []
        if team_id is not None:
            team_ids.append(team_id)
        if user_arg is not None:
            user = self._resolve_user(user_arg)
            user_team_ids = list(Team.objects.filter(organization__members=user).values_list("id", flat=True))
            if not user_team_ids:
                self.stdout.write(self.style.WARNING(f"User {user_arg!r} belongs to no teams; nothing to clear."))
                return
            team_ids.extend(user_team_ids)

        if team_ids:
            qs = qs.filter(team_id__in=team_ids)

        if workflow_id:
            qs = qs.filter(workflow_id=workflow_id)
        if skill_id:
            qs = qs.filter(skill_id=skill_id)
        if session_id:
            qs = qs.filter(session_id=session_id)

        # Materialize counts + identifiers up front so dry-run and the actual
        # delete print the same numbers.
        matches = list(qs.values("session_id", "team_id", "workflow_id", "skill_id", "run_phase"))
        count = len(matches)

        if count == 0:
            self.stdout.write("No matching wizard sessions found.")
            return

        if dry_run:
            self.stdout.write(self.style.NOTICE(f"[dry-run] Would delete {count} wizard session(s):"))
            for row in matches:
                self.stdout.write(
                    f"  - team={row['team_id']} workflow={row['workflow_id']} skill={row['skill_id']} "
                    f"phase={row['run_phase']} session_id={row['session_id']}"
                )
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} wizard session row(s)."))

    @staticmethod
    def _resolve_user(value: str) -> User:
        # Numeric → primary key lookup; otherwise treat as email.
        if value.isdigit():
            try:
                return User.objects.get(pk=int(value))
            except User.DoesNotExist as e:
                raise CommandError(f"No user with id={value}") from e
        try:
            return User.objects.get(email=value)
        except User.DoesNotExist as e:
            raise CommandError(f"No user with email={value!r}") from e
