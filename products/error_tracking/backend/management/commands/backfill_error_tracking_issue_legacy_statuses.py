"""Backfill error tracking issues stuck on legacy `archived` or `pending_release` statuses to `resolved`.

Both statuses were defined on `ErrorTrackingIssue.Status` but are no longer reachable from
the PostHog UI — `archived` was used by a short-lived "Archive" button (Sep 2024 to Mar 2025)
and later by an MCP tool, and `pending_release` was never wired up in the UI. The model
still accepts both values via direct API writes, and a small number of rows ended up with
them across teams.

The fix is to migrate those rows to `resolved`, which most closely matches the cymbal
"re-activate on next fingerprint" semantics so user-observable behavior is preserved. The
companion serializer-level change rejects new writes of these values, so this backfill is
a one-shot cleanup that becomes idempotent (re-running on a clean dataset is a no-op).

Usage:
    # Dry-run (default) — counts rows per team, writes nothing
    python manage.py backfill_error_tracking_issue_legacy_statuses

    # Live run — updates Postgres and re-syncs to ClickHouse
    python manage.py backfill_error_tracking_issue_legacy_statuses --live-run

    # Specific team
    python manage.py backfill_error_tracking_issue_legacy_statuses --live-run --team-id 2

    # Resume from a specific team_id (inclusive)
    python manage.py backfill_error_tracking_issue_legacy_statuses --live-run --start-from-team-id 1234

    # Limit to a single legacy status
    python manage.py backfill_error_tracking_issue_legacy_statuses --live-run --status archived
"""

from __future__ import annotations

import time
import logging
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import transaction

import structlog

from products.error_tracking.backend.models import ErrorTrackingIssue, sync_issues_to_clickhouse

logger = structlog.get_logger(__name__)

LEGACY_STATUSES: tuple[str, ...] = (
    ErrorTrackingIssue.Status.ARCHIVED,
    ErrorTrackingIssue.Status.PENDING_RELEASE,
)
TARGET_STATUS = ErrorTrackingIssue.Status.RESOLVED


class Command(BaseCommand):
    help = "Backfill error tracking issues stuck on legacy archived/pending_release statuses to resolved."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually update rows and re-sync to ClickHouse (default is dry-run).",
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
        parser.add_argument(
            "--status",
            type=str,
            default=None,
            choices=list(LEGACY_STATUSES),
            help="Limit to a single legacy status (default: both archived and pending_release).",
        )

    def handle(
        self,
        *,
        live_run: bool,
        team_id: int | None,
        start_from_team_id: int | None,
        end_team_id: int | None,
        status: str | None,
        **options,
    ):
        logger.setLevel(logging.INFO)

        statuses = (status,) if status else LEGACY_STATUSES
        mode = "LIVE" if live_run else "DRY-RUN (use --live-run to apply)"
        logger.info("backfill_starting", mode=mode, statuses=list(statuses))

        per_team_counts = self._summarize(
            statuses=statuses,
            team_id=team_id,
            start_from_team_id=start_from_team_id,
            end_team_id=end_team_id,
        )

        total = sum(per_team_counts.values())
        logger.info("backfill_summary", teams=len(per_team_counts), total_issues=total)

        if total == 0:
            logger.info("backfill_no_rows_found")
            return

        for tid, count in sorted(per_team_counts.items()):
            logger.info("backfill_team_pending", team_id=tid, issue_count=count)

        if not live_run:
            logger.info("backfill_dry_run_complete", total=total)
            return

        start_time = time.monotonic()
        updated_total = 0
        for tid in sorted(per_team_counts):
            updated = self._backfill_team(team_id=tid, statuses=statuses)
            updated_total += updated
            logger.info("backfill_team_done", team_id=tid, updated=updated)

        elapsed = time.monotonic() - start_time
        logger.info("backfill_complete", updated=updated_total, elapsed_s=round(elapsed, 2))

    def _summarize(
        self,
        *,
        statuses: tuple[str, ...],
        team_id: int | None,
        start_from_team_id: int | None,
        end_team_id: int | None,
    ) -> dict[int, int]:
        qs = ErrorTrackingIssue.objects.filter(status__in=statuses)
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        else:
            if start_from_team_id is not None:
                qs = qs.filter(team_id__gte=start_from_team_id)
            if end_team_id is not None:
                qs = qs.filter(team_id__lte=end_team_id)

        counts: dict[int, int] = {}
        for tid in qs.values_list("team_id", flat=True):
            counts[tid] = counts.get(tid, 0) + 1
        return counts

    def _backfill_team(self, *, team_id: int, statuses: tuple[str, ...]) -> int:
        with transaction.atomic():
            issue_ids = self._get_legacy_issue_ids_for_update(team_id=team_id, statuses=statuses)
            if not issue_ids:
                return 0

            updated_issue_ids = list(
                ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids, status__in=statuses).values_list(
                    "id", flat=True
                )
            )
            if not updated_issue_ids:
                return 0

            # Emit while the legacy status is still a durable retry marker.
            # sync_issues_to_clickhouse maps deprecated statuses to resolved.
            sync_issues_to_clickhouse(issue_ids=updated_issue_ids, team_id=team_id)

            # Skip ModelActivityMixin signals — this is a janitorial fix, not user activity.
            updated = ErrorTrackingIssue.objects.filter(
                team_id=team_id, id__in=updated_issue_ids, status__in=statuses
            ).update(status=TARGET_STATUS)
            return updated

    def _get_legacy_issue_ids_for_update(self, *, team_id: int, statuses: tuple[str, ...]) -> list[UUID]:
        return list(
            ErrorTrackingIssue.objects.select_for_update()
            .filter(team_id=team_id, status__in=statuses)
            .values_list("id", flat=True)
        )
