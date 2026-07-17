"""Backfill exception-autocapture opt-in from Team into ErrorTrackingSettings.

The toggle is moving off `Team.autocapture_exceptions_opt_in` onto
`ErrorTrackingSettings.autocapture_exceptions_opt_in` (Phase 1 of the move). A `post_save`
signal on Team dual-writes new changes; this command backfills teams that opted in before
that signal was deployed. Only teams that have opted in need a row: a missing row or a null
column both read as disabled, which already matches every team that never opted in, so
those teams are deliberately left untouched.

The candidate id list is only a starting point. To avoid clobbering a live disable with a
stale snapshot, each batch re-reads the teams that are *still* opted in under a `Team` row
lock (`select_for_update`) and upserts only those inside the same transaction. The lock
serializes the batch against a concurrent disabling `Team.save()`: the disable either commits
first (so the re-read skips the team) or blocks until the batch commits (so its own signal
then corrects the row we just wrote). `Team` stays the single source of truth.

Idempotent — re-running writes the same `True` and is a no-op on a clean dataset.

Usage:
    # Dry-run (default) — counts teams, writes nothing
    python manage.py backfill_error_tracking_autocapture_opt_in

    # Live run
    python manage.py backfill_error_tracking_autocapture_opt_in --live-run

    # Specific team
    python manage.py backfill_error_tracking_autocapture_opt_in --live-run --team-id 2

    # Resume from a specific team_id (inclusive)
    python manage.py backfill_error_tracking_autocapture_opt_in --live-run --start-from-team-id 1234
"""

from __future__ import annotations

import time
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import structlog

from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingSettings

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 100


class Command(BaseCommand):
    help = "Backfill exception-autocapture opt-in from Team onto ErrorTrackingSettings for opted-in teams."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually write rows (default is dry-run).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Teams per batch (default {DEFAULT_BATCH_SIZE}). Each batch re-reads live state before writing.",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Backfill only this team.",
        )
        parser.add_argument(
            "--start-from-team-id",
            type=int,
            default=None,
            help="Resume from this team_id (inclusive). Skips all teams with id < this value. Ignored when --team-id is set.",
        )
        parser.add_argument(
            "--end-team-id",
            type=int,
            default=None,
            help="Only include teams with team_id <= this value (inclusive). Ignored when --team-id is set.",
        )

    def handle(
        self,
        *,
        live_run: bool,
        batch_size: int,
        team_id: int | None,
        start_from_team_id: int | None,
        end_team_id: int | None,
        **options,
    ):
        logger.setLevel(logging.INFO)

        if batch_size < 1:
            raise CommandError(f"--batch-size must be a positive integer, got {batch_size}.")

        mode = "LIVE" if live_run else "DRY-RUN (use --live-run to apply)"
        candidate_ids = self._candidate_team_ids(
            team_id=team_id,
            start_from_team_id=start_from_team_id,
            end_team_id=end_team_id,
        )
        logger.info("backfill_starting", mode=mode, batch_size=batch_size, candidate_teams=len(candidate_ids))

        if not candidate_ids:
            logger.info("backfill_no_rows_found")
            return

        if not live_run:
            logger.info("backfill_dry_run_complete", teams=len(candidate_ids))
            return

        start_time = time.monotonic()
        synced = 0
        for offset in range(0, len(candidate_ids), batch_size):
            chunk = candidate_ids[offset : offset + batch_size]
            synced += self._sync_batch(chunk)
            logger.info("backfill_progress", processed=offset + len(chunk), synced=synced, last_team_id=chunk[-1])

        elapsed = time.monotonic() - start_time
        logger.info("backfill_complete", synced=synced, elapsed_s=round(elapsed, 2))

    def _sync_batch(self, team_ids: list[int]) -> int:
        # Lock the Team rows while re-reading live state, then upsert in the same transaction. The
        # lock serializes this batch against a concurrent disabling Team.save(): the disable either
        # commits first (so we read False and skip the team) or blocks until we commit (so its signal
        # then flips the row we wrote to False). A team no longer opted in and still row-less is
        # already correct (row-less == disabled), so skipping it is right.
        with transaction.atomic():
            still_opted_in = list(
                Team.objects.select_for_update()
                .filter(id__in=team_ids, autocapture_exceptions_opt_in=True)
                .values_list("id", flat=True)
            )
            if not still_opted_in:
                return 0

            ErrorTrackingSettings.objects.bulk_create(
                [ErrorTrackingSettings(team_id=tid, autocapture_exceptions_opt_in=True) for tid in still_opted_in],
                update_conflicts=True,
                unique_fields=["team"],
                update_fields=["autocapture_exceptions_opt_in"],
            )
            return len(still_opted_in)

    def _candidate_team_ids(
        self,
        *,
        team_id: int | None,
        start_from_team_id: int | None,
        end_team_id: int | None,
    ) -> list[int]:
        qs = Team.objects.filter(autocapture_exceptions_opt_in=True)
        if team_id is not None:
            qs = qs.filter(id=team_id)
        else:
            if start_from_team_id is not None:
                qs = qs.filter(id__gte=start_from_team_id)
            if end_team_id is not None:
                qs = qs.filter(id__lte=end_team_id)
        return sorted(qs.values_list("id", flat=True))
