"""Set OrganizationFeatureFlagsConfig.flag_evaluations_mode on the selected organizations.

New organizations take FLAG_EVALUATIONS_NEW_ORG_MODE when they are created. This command covers
the organizations that existed before that setting changed: a list of ids, or every organization
created after an instant.

Ingestion does not act on mode 2 yet. An organization set to 2 now behaves as mode 1, and it stops
writing $feature_flag_called to events on its own when that support deploys.
"""

import argparse
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.flag_evaluations_mode import (
    UnknownIdsError,
    get_organizations,
    select_organizations,
    set_organization_flag_evaluations_mode,
)


def _parse_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not an ISO 8601 date or datetime") from error
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = "Set the flag_evaluations mode of the selected organizations"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--mode",
            type=int,
            required=True,
            choices=FlagEvaluationsMode.values,
            help=(
                "0 reads events, 1 reads flag_evaluations, 2 also stops writing flag calls to events. "
                "Ingestion does not act on mode 2 yet, so an organization on mode 2 behaves as mode 1 "
                "until that ships. "
                "flag_evaluations holds rows only from the day ingestion started writing them "
                "(2026-09-09 for PostHog Cloud), so on mode 1 or 2 the Usage tab shows no data for earlier days."
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
                "Also lower organizations that are above --mode. Once ingestion acts on mode 2, lowering "
                "from mode 2 leaves a gap in the events table."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        mode = FlagEvaluationsMode(options["mode"])
        dry_run: bool = options["dry_run"]
        allow_downgrade: bool = options["allow_downgrade"]
        organization_ids: list[UUID] | None = options["organization_ids"]

        if organization_ids is None:
            organizations = list(select_organizations(created_after=options["created_after"]))
        else:
            try:
                organizations = get_organizations(organization_ids)
            except UnknownIdsError as error:
                raise CommandError(str(error)) from error

        verb = "Would set" if dry_run else "Set"
        self.stdout.write(f"{verb} mode {mode.value} ({mode.label}) on {len(organizations)} organization(s).")
        changed_count = 0
        left_above_count = 0
        stopped_experiments_count = 0
        with transaction.atomic():
            for organization in organizations:
                change = set_organization_flag_evaluations_mode(
                    organization, mode, allow_downgrade=allow_downgrade, dry_run=dry_run
                )
                changed_count += change.changed
                left_above_count += change.left_above_mode
                if change.changed and mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY:
                    stopped_experiments_count += change.running_experiments_on_feature_flag_called
                outcome = (
                    f"mode {change.current_mode} -> {change.target_mode}"
                    if change.changed
                    else f"mode {change.current_mode}, unchanged"
                )
                self.stdout.write(
                    f"  organization {change.organization_id} (created {change.organization_created_at:%Y-%m-%d}, "
                    f"{change.team_count} team(s), "
                    f"{change.running_experiments_on_feature_flag_called} experiment(s) on $feature_flag_called): {outcome}"
                )

        self.stdout.write(f"{verb} mode {mode.value} on {changed_count} organization(s).")
        if left_above_count:
            self.stdout.write(
                f"Left {left_above_count} organization(s) above mode {mode.value}. "
                "Pass --allow-downgrade to lower them."
            )
        if stopped_experiments_count:
            self.stdout.write(
                f"{stopped_experiments_count} running experiment(s) count exposures on $feature_flag_called. "
                "On teams in the ingestion allowlist, those exposures stop on this mode."
            )
