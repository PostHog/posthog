"""Backfill exception-autocapture opt-in from Team into ErrorTrackingSettings.

The toggle is moving off `Team.autocapture_exceptions_opt_in` onto
`ErrorTrackingSettings.autocapture_exceptions_opt_in` (Phase 1 of the move). A `post_save`
signal on Team dual-writes new changes; this command backfills teams that opted in before
that signal was deployed. Only teams that have opted in need a row: a missing row or a null
column both read as disabled, which already matches every team that never opted in, so
those teams are deliberately left untouched.

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

from django.core.management.base import BaseCommand

import structlog

from posthog.models import Team

from products.error_tracking.backend.models import sync_autocapture_opt_in

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill exception-autocapture opt-in from Team onto ErrorTrackingSettings for opted-in teams."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually write rows (default is dry-run).",
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
            help="Resume from this team_id (inclusive). Skips all teams with id < this value.",
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
        team_id: int | None,
        start_from_team_id: int | None,
        end_team_id: int | None,
        **options,
    ):
        logger.setLevel(logging.INFO)

        mode = "LIVE" if live_run else "DRY-RUN (use --live-run to apply)"
        team_ids = self._opted_in_team_ids(
            team_id=team_id,
            start_from_team_id=start_from_team_id,
            end_team_id=end_team_id,
        )
        logger.info("backfill_starting", mode=mode, opted_in_teams=len(team_ids))

        if not team_ids:
            logger.info("backfill_no_rows_found")
            return

        if not live_run:
            logger.info("backfill_dry_run_complete", teams=len(team_ids))
            return

        start_time = time.monotonic()
        for tid in team_ids:
            sync_autocapture_opt_in(team_id=tid, opt_in=True)

        elapsed = time.monotonic() - start_time
        logger.info("backfill_complete", synced=len(team_ids), elapsed_s=round(elapsed, 2))

    def _opted_in_team_ids(
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
