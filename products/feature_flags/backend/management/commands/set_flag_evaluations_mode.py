"""Set TeamFeatureFlagsConfig.flag_evaluations_mode on every team of the selected organizations.

New organizations take FLAG_EVALUATIONS_NEW_ORG_MODE when their first team is created. This
command covers the organizations that existed before that setting changed: a list of ids, or every
organization created after an instant. Run audit_flag_evaluations_mode after it.

Ingestion does not act on mode 2 yet. A team set to 2 now behaves as mode 1, and it stops writing
$feature_flag_called to events on its own when that support deploys.
"""

import argparse
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.feature_flags.backend.flag_evaluations_mode import (
    select_organizations,
    set_organization_flag_evaluations_mode,
)
from products.feature_flags.backend.models.team_feature_flags_config import FlagEvaluationsMode


def _parse_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not an ISO 8601 date or datetime") from error
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = "Set the flag_evaluations mode on every team of the selected organizations"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--mode",
            type=int,
            required=True,
            choices=FlagEvaluationsMode.values,
            help=(
                "0 reads events, 1 reads flag_evaluations, 2 also stops writing flag calls to events. "
                "Ingestion does not act on mode 2 yet, so a team on mode 2 behaves as mode 1 until that ships."
            ),
        )
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument(
            "--organization-id",
            type=UUID,
            action="append",
            dest="organization_ids",
            help="Organization to update. Repeat the flag for more than one.",
        )
        selector.add_argument(
            "--organizations-created-after",
            type=_parse_instant,
            dest="created_after",
            help="Update every organization created after this ISO 8601 instant. A bare date means midnight UTC.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report the changes and write nothing")
        parser.add_argument(
            "--allow-downgrade",
            action="store_true",
            help=(
                "Also lower teams that are above --mode. Once ingestion acts on mode 2, lowering from mode 2 "
                "leaves a gap in the events table."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        mode = FlagEvaluationsMode(options["mode"])
        dry_run: bool = options["dry_run"]
        allow_downgrade: bool = options["allow_downgrade"]
        organization_ids: list[UUID] | None = options["organization_ids"]

        organizations = list(
            select_organizations(organization_ids=organization_ids, created_after=options["created_after"])
        )
        if organization_ids is not None:
            missing = set(organization_ids) - {organization.id for organization in organizations}
            if missing:
                # Fail before writing anything, so a mistyped id does not leave a partial run.
                raise CommandError(f"Unknown organization id(s): {', '.join(sorted(map(str, missing)))}")

        verb = "Would set" if dry_run else "Set"
        self.stdout.write(f"{verb} mode {mode.value} ({mode.label}) on {len(organizations)} organization(s).")
        teams_changed = 0
        teams_skipped = 0
        for organization in organizations:
            change = set_organization_flag_evaluations_mode(
                organization, mode, allow_downgrade=allow_downgrade, dry_run=dry_run
            )
            teams_changed += change.teams_below_mode + (change.teams_above_mode if allow_downgrade else 0)
            teams_skipped += 0 if allow_downgrade else change.teams_above_mode
            self.stdout.write(
                f"  organization {change.organization_id} (created {change.organization_created_at:%Y-%m-%d}): "
                f"{change.team_count} team(s), {change.teams_below_mode} below, {change.teams_at_mode} at, "
                f"{change.teams_above_mode} above mode {mode.value}"
            )

        self.stdout.write(f"{verb} mode {mode.value} on {teams_changed} team(s).")
        if teams_skipped:
            self.stdout.write(
                f"Left {teams_skipped} team(s) above mode {mode.value}. Pass --allow-downgrade to lower them."
            )
