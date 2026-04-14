"""Backfill the error_tracking_fingerprint_issue_state ClickHouse table from Postgres.

Reads all fingerprint-to-issue mappings (with issue metadata and assignments) from
Postgres and produces them to Kafka, where the normal MV pipeline inserts them into
the ReplacingMergeTree table.

Usage:
    # Dry-run (default) — counts rows, produces nothing
    python manage.py backfill_error_tracking_issue_state

    # Live run — produces to Kafka
    python manage.py backfill_error_tracking_issue_state --live-run

    # Specific team
    python manage.py backfill_error_tracking_issue_state --live-run --team-id 2

    # Resume from a specific team (skips teams with id < start value)
    python manage.py backfill_error_tracking_issue_state --live-run --start-from-team-id 1234

    # Stop at a team id (inclusive); combine with --start-from-team-id for a range
    python manage.py backfill_error_tracking_issue_state --live-run --end-team-id 9999

    # Custom batch size
    python manage.py backfill_error_tracking_issue_state --live-run --batch-size 10000
"""

from __future__ import annotations

import time
import logging

from django.core.management.base import BaseCommand

import structlog

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE
from posthog.models.event.util import format_clickhouse_timestamp

from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2
from products.error_tracking.backend.sql import INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 5000


class Command(BaseCommand):
    help = "Backfill error_tracking_fingerprint_issue_state ClickHouse table from Postgres."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually produce to Kafka (default is dry-run).",
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
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of fingerprints to fetch per Postgres query (default: {DEFAULT_BATCH_SIZE}).",
        )

    def handle(
        self,
        *,
        live_run: bool,
        team_id: int | None,
        start_from_team_id: int | None,
        end_team_id: int | None,
        batch_size: int,
        **options,
    ):
        logger.setLevel(logging.INFO)

        if live_run:
            logger.info("backfill_starting", mode="LIVE")
        else:
            logger.info("backfill_starting", mode="DRY-RUN (use --live-run to produce)")

        team_ids = self._get_team_ids(team_id=team_id, start_from_team_id=start_from_team_id, end_team_id=end_team_id)
        logger.info("backfill_teams_found", count=len(team_ids))

        total_count = self._build_queryset(
            team_id=team_id, start_from_team_id=start_from_team_id, end_team_id=end_team_id
        ).count()
        logger.info("backfill_total_fingerprints", count=total_count)

        if not live_run:
            logger.info("backfill_dry_run_complete", total=total_count)
            return

        producer = ClickhouseProducer()
        produced = 0
        since_last_flush = 0
        start_time = time.monotonic()

        for current_team_id in team_ids:
            team_qs = self._build_queryset(team_id=current_team_id).iterator(chunk_size=batch_size)
            logger.info("backfill_processing_team", team_id=current_team_id, produced_so_far=produced)

            for fp in team_qs:
                data = self._build_row(fp)
                producer.produce(
                    sql=INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
                    topic=KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
                    data=data,
                )

                produced += 1
                since_last_flush += 1

                if since_last_flush >= batch_size:
                    if producer.producer is not None:
                        producer.producer.flush()
                    since_last_flush = 0
                    elapsed = time.monotonic() - start_time
                    rate = produced / elapsed if elapsed > 0 else 0
                    logger.info(
                        "backfill_progress",
                        produced=produced,
                        total=total_count,
                        percent=round(produced / total_count * 100, 1) if total_count > 0 else 0,
                        rate=round(rate),
                        elapsed_s=round(elapsed),
                    )

        if producer.producer is not None:
            producer.producer.flush()
        elapsed = time.monotonic() - start_time
        logger.info("backfill_complete", produced=produced, elapsed_s=round(elapsed))

    def _get_team_ids(
        self, *, team_id: int | None, start_from_team_id: int | None, end_team_id: int | None
    ) -> list[int]:
        if team_id is not None:
            return [team_id]

        qs = ErrorTrackingIssueFingerprintV2.objects.all()
        if start_from_team_id is not None:
            qs = qs.filter(team_id__gte=start_from_team_id)
        if end_team_id is not None:
            qs = qs.filter(team_id__lte=end_team_id)

        return list(qs.values_list("team_id", flat=True).distinct().order_by("team_id"))

    def _build_queryset(
        self, *, team_id: int | None = None, start_from_team_id: int | None = None, end_team_id: int | None = None
    ):
        qs = ErrorTrackingIssueFingerprintV2.objects.select_related("issue", "issue__assignment")

        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        else:
            if start_from_team_id is not None:
                qs = qs.filter(team_id__gte=start_from_team_id)
            if end_team_id is not None:
                qs = qs.filter(team_id__lte=end_team_id)

        return qs

    def _build_row(self, fp: ErrorTrackingIssueFingerprintV2) -> dict:
        issue = fp.issue
        assignment = getattr(issue, "assignment", None)

        assigned_user_id: int | None = None
        assigned_role_id: str | None = None
        if assignment is not None:
            if assignment.user_id:
                assigned_user_id = assignment.user_id
            elif assignment.role_id:
                assigned_role_id = str(assignment.role_id)

        first_seen_raw = fp.first_seen or issue.created_at
        first_seen = format_clickhouse_timestamp(first_seen_raw) if first_seen_raw else None
        version = int(fp.created_at.timestamp() * 1000)

        return {
            "team_id": fp.team_id,
            "fingerprint": fp.fingerprint,
            "issue_id": str(issue.id),
            "issue_name": issue.name,
            "issue_description": issue.description,
            "issue_status": issue.status,
            "assigned_user_id": assigned_user_id,
            "assigned_role_id": assigned_role_id,
            "first_seen": first_seen,
            "is_deleted": 0,
            "version": version,
        }
