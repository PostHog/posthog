"""Set OrganizationFeatureFlagsConfig.flag_evaluations_mode on the selected organizations.

New organizations take FLAG_EVALUATIONS_NEW_ORG_MODE when they are created. This command covers
the organizations that existed before that setting changed: a list of ids, every organization
created after an instant, or every organization, less an optional exclude list.

The command writes the organizations in chunks and commits each chunk in its own transaction.
Without --allow-downgrade a write only raises a mode, so a run that fails partway resumes when it
runs again. --write-changed-ids appends the ids of each committed chunk's changed organizations to
a file. A rollback passes that file to --organization-ids-file.

On mode 2, ingestion stops writing $feature_flag_called to events for the organization's teams that it
copies to flag_evaluations.
"""

import os
import math
import time
import argparse
from collections.abc import Iterable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog.models import Organization

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.flag_evaluations_mode import (
    FLAG_EVALUATIONS_MODES_HELP,
    OrganizationModeChange,
    UnknownIdsError,
    find_unknown_organization_ids,
    select_organization_ids,
    set_organizations_flag_evaluations_mode,
)


def _parse_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not an ISO 8601 date or datetime") from error
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not a positive integer")
    return parsed


def _read_ids_file(path: Path) -> list[UUID]:
    """One UUID per line. Blank lines are skipped, and any other line that is not a UUID fails the run."""
    ids = []
    try:
        with path.open() as file:
            for line_number, line in enumerate(file, start=1):
                if not (text := line.strip()):
                    continue
                try:
                    ids.append(UUID(text))
                except ValueError as error:
                    raise CommandError(f"{path}:{line_number}: {text!r} is not an organization id") from error
    except OSError as error:
        raise CommandError(f"Cannot read {path}: {error}") from error
    return ids


def _sync(file: TextIO) -> None:
    file.flush()
    os.fsync(file.fileno())


class Command(BaseCommand):
    help = "Set the flag_evaluations mode of the selected organizations"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--mode",
            type=int,
            required=True,
            choices=FlagEvaluationsMode.values,
            help=FLAG_EVALUATIONS_MODES_HELP,
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
            "--organization-ids-file",
            type=Path,
            help="File with one organization id per line. An unknown id fails the run before any write.",
        )
        selector.add_argument(
            "--organizations-created-after",
            type=_parse_instant,
            dest="created_after",
            help="Update every organization created after this ISO 8601 instant. A bare date means midnight UTC.",
        )
        selector.add_argument("--all-organizations", action="store_true", help="Update every organization.")
        parser.add_argument(
            "--exclude-organization-ids-file",
            type=Path,
            help=(
                "File with one organization id per line. The run skips these organizations. An unknown id fails "
                "the run before any write."
            ),
        )
        parser.add_argument(
            "--chunk-size",
            type=_positive_int,
            default=1000,
            help=(
                "Organizations per transaction. A failure rolls back only its own chunk, and running the command "
                "again resumes the run. A run larger than one chunk prints a line per chunk instead of one per "
                "organization."
            ),
        )
        parser.add_argument(
            "--skip-experiment-count",
            action="store_true",
            help=(
                "Skip the count of running experiments that read $feature_flag_called from events. The count "
                "takes queries for each organization and only feeds a warning."
            ),
        )
        parser.add_argument(
            "--write-changed-ids",
            type=Path,
            help=(
                "Append the ids of the organizations that the run changed to this file, one per line. Each chunk "
                "writes its ids before it commits and removes them again when it fails. A rerun with the same path "
                "appends the ids it changes. Refused with --dry-run."
            ),
        )
        parser.add_argument(
            "--skip-unknown-organization-ids",
            action="store_true",
            help=(
                "Skip listed ids that match no organization instead of failing the run. A rollback from a "
                "--write-changed-ids file needs it when an organization was deleted after the run."
            ),
        )
        parser.add_argument("--dry-run", action="store_true", help="Report the changes and write nothing")
        parser.add_argument(
            "--allow-downgrade",
            action="store_true",
            help=(
                "Also lower organizations that are above --mode. Lowering an organization from mode 2 restarts "
                "the events writes that ingestion stopped for its teams. The events table keeps a gap for those "
                "teams for the time the organization spent on 2."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        mode = FlagEvaluationsMode(options["mode"])
        dry_run: bool = options["dry_run"]
        allow_downgrade: bool = options["allow_downgrade"]
        chunk_size: int = options["chunk_size"]
        count_experiments = not options["skip_experiment_count"]
        changed_ids_path: Path | None = options["write_changed_ids"]
        if dry_run and changed_ids_path is not None:
            raise CommandError("--write-changed-ids writes the ids a run changed, and a dry run changes none")

        skip_unknown: bool = options["skip_unknown_organization_ids"]
        organization_ids = self._select(options, skip_unknown=skip_unknown)
        exclude_path: Path | None = options["exclude_organization_ids_file"]
        if exclude_path is not None:
            excluded_ids = set(
                self._known(_read_ids_file(exclude_path), skip_unknown=skip_unknown, source=str(exclude_path))
            )
            selected_count = len(organization_ids)
            organization_ids = [
                organization_id for organization_id in organization_ids if organization_id not in excluded_ids
            ]
            self.stdout.write(
                f"Excluded {selected_count - len(organization_ids)} selected organization(s) of the "
                f"{len(excluded_ids)} in {exclude_path}."
            )

        verb = "Would set" if dry_run else "Set"
        self.stdout.write(f"{verb} mode {mode.value} ({mode.label}) on {len(organization_ids)} organization(s).")
        if not count_experiments:
            self.stdout.write("Skipping the count of running experiments that read $feature_flag_called from events.")

        per_organization_lines = len(organization_ids) <= chunk_size
        chunk_total = math.ceil(len(organization_ids) / chunk_size)
        done_count = 0
        changed_count = 0
        left_above_count = 0
        experiments_needing_flag_calls_count = 0
        started_at = time.monotonic()
        with self._open_changed_ids_file(changed_ids_path) as changed_ids_file:
            for chunk_number, chunk_ids in enumerate(batched(organization_ids, chunk_size, strict=False), start=1):
                # An organization deleted after the selection drops out of its chunk instead of failing the run.
                organizations = list(
                    Organization.objects.filter(id__in=chunk_ids)
                    .only("id", "name", "created_at")
                    .order_by("created_at", "id")
                )
                chunk_start = changed_ids_file.tell() if changed_ids_file is not None else 0
                try:
                    with transaction.atomic():
                        changes = set_organizations_flag_evaluations_mode(
                            organizations,
                            mode,
                            allow_downgrade=allow_downgrade,
                            dry_run=dry_run,
                            count_experiments=count_experiments,
                        )
                        # The ids reach the disk before the chunk commits. A rerun reports a committed
                        # organization as unchanged, so it could not list an id that a crash after the
                        # commit lost.
                        if changed_ids_file is not None:
                            changed_ids_file.writelines(
                                f"{change.organization_id}\n" for change in changes if change.changed
                            )
                            _sync(changed_ids_file)
                except BaseException:
                    if changed_ids_file is not None:
                        changed_ids_file.truncate(chunk_start)
                        _sync(changed_ids_file)
                    raise

                done_count += len(chunk_ids)
                for change in changes:
                    changed_count += change.changed
                    left_above_count += change.left_above_mode
                    if change.changed and mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY:
                        experiments_needing_flag_calls_count += change.running_experiments_needing_flag_calls_in_events
                    if per_organization_lines:
                        self._write_organization_line(change, count_experiments=count_experiments)
                if not per_organization_lines:
                    self.stdout.write(
                        f"  chunk {chunk_number}/{chunk_total}: {done_count}/{len(organization_ids)} organization(s) "
                        f"done, {changed_count} changed, {time.monotonic() - started_at:.0f}s elapsed"
                    )

        self.stdout.write(f"{verb} mode {mode.value} on {changed_count} organization(s).")
        if changed_ids_path is not None:
            self.stdout.write(f"Appended {changed_count} changed organization id(s) to {changed_ids_path}.")
        if left_above_count:
            self.stdout.write(
                f"Left {left_above_count} organization(s) above mode {mode.value}. "
                "Pass --allow-downgrade to lower them."
            )
        if experiments_needing_flag_calls_count:
            self.stdout.write(
                f"{experiments_needing_flag_calls_count} running experiment(s) read $feature_flag_called from events "
                "through an exposure action, an activation, or a metric. Those reads find no new calls on this mode."
            )

    def _select(self, options: dict[str, Any], *, skip_unknown: bool) -> list[UUID]:
        if options["all_organizations"] or options["created_after"] is not None:
            return select_organization_ids(created_after=options["created_after"])
        ids_file: Path | None = options["organization_ids_file"]
        if ids_file is None:
            return self._known(options["organization_ids"], skip_unknown=skip_unknown, source="--organization-id")
        return self._known(_read_ids_file(ids_file), skip_unknown=skip_unknown, source=str(ids_file))

    def _known(self, organization_ids: Iterable[UUID], *, skip_unknown: bool, source: str) -> list[UUID]:
        """The given ids, once each and in order, less those that match no organization when skip_unknown is set."""
        unique_ids = list(dict.fromkeys(organization_ids))
        if not (missing_ids := find_unknown_organization_ids(unique_ids)):
            return unique_ids
        if not skip_unknown:
            raise CommandError(str(UnknownIdsError("organization", missing_ids)))
        self.stdout.write(f"Skipping {len(missing_ids)} unknown organization id(s) in {source}.")
        return [organization_id for organization_id in unique_ids if organization_id not in missing_ids]

    def _open_changed_ids_file(self, path: Path | None) -> AbstractContextManager[TextIO | None]:
        if path is None:
            return nullcontext()
        try:
            file = path.open("a+")
        except OSError as error:
            raise CommandError(f"Cannot open {path}: {error}") from error
        file.seek(0)
        if listed_count := sum(1 for line in file if line.strip()):
            self.stdout.write(f"Appending to {path}, which lists {listed_count} organization id(s) already.")
        file.seek(0, os.SEEK_END)
        return file

    def _write_organization_line(self, change: OrganizationModeChange, *, count_experiments: bool) -> None:
        outcome = (
            f"mode {change.current_mode} -> {change.target_mode}"
            if change.changed
            else f"mode {change.current_mode}, unchanged"
        )
        experiments = (
            f", {change.running_experiments_needing_flag_calls_in_events} experiment(s) reading $feature_flag_called "
            "from events"
            if count_experiments
            else ""
        )
        self.stdout.write(
            f"  organization {change.organization_id} (created {change.organization_created_at:%Y-%m-%d}, "
            f"{change.team_count} team(s){experiments}): {outcome}"
        )
