"""Sanitize Git remote URLs stored in error tracking release metadata.

Run this command after the release write sanitizer is deployed so concurrent writes cannot
reintroduce credentials behind the backfill cursor.

Usage:
    python manage.py backfill_error_tracking_release_metadata
    python manage.py backfill_error_tracking_release_metadata --live-run
    python manage.py backfill_error_tracking_release_metadata --live-run --batch-size 500
    python manage.py backfill_error_tracking_release_metadata --live-run --start-after-id <release-uuid>
"""

from __future__ import annotations

import logging
from argparse import ArgumentParser
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet

import structlog

from products.error_tracking.backend.logic import sanitize_release_metadata
from products.error_tracking.backend.models import ErrorTrackingRelease

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 1_000
SANITIZABLE_REMOTE_URL_PATTERN = r"^(//|[^/?#]+://)[^/?#]*@|[?#]"


class Command(BaseCommand):
    help = "Remove credentials, query parameters, and fragments from stored error tracking release Git remotes."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Update stored release metadata. The default is a dry run.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of matching releases to process per transaction. The default is {DEFAULT_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--start-after-id",
            type=UUID,
            default=None,
            help="Resume after this release UUID.",
        )

    def handle(
        self,
        *,
        live_run: bool,
        batch_size: int,
        start_after_id: UUID | None,
        **options: object,
    ) -> None:
        logger.setLevel(logging.INFO)
        if batch_size <= 0:
            raise CommandError("Batch size must be greater than zero.")

        end_id = ErrorTrackingRelease.objects.order_by("-id").values_list("id", flat=True).first()
        if end_id is None or (start_after_id is not None and start_after_id >= end_id):
            logger.info("release_metadata_backfill_complete", matched=0, updated=0)
            return

        mode = "LIVE" if live_run else "DRY-RUN"
        logger.info(
            "release_metadata_backfill_starting",
            mode=mode,
            batch_size=batch_size,
            start_after_id=str(start_after_id) if start_after_id is not None else None,
            end_id=str(end_id),
        )

        matched_total = 0
        updated_total = 0
        cursor = start_after_id
        while candidate_ids := self._get_candidate_ids(after_id=cursor, end_id=end_id, batch_size=batch_size):
            cursor = candidate_ids[-1]
            matched_total += len(candidate_ids)
            if live_run:
                updated_total += self._sanitize_releases(candidate_ids)

            logger.info(
                "release_metadata_backfill_progress",
                matched=matched_total,
                updated=updated_total,
                last_release_id=str(cursor),
            )

        logger.info(
            "release_metadata_backfill_complete",
            matched=matched_total,
            updated=updated_total,
            last_release_id=str(cursor) if cursor is not None else None,
        )

    def _get_candidate_ids(self, *, after_id: UUID | None, end_id: UUID, batch_size: int) -> list[UUID]:
        candidates = ErrorTrackingRelease.objects.filter(
            id__lte=end_id,
            metadata__git__remote_url__regex=SANITIZABLE_REMOTE_URL_PATTERN,
        )
        if after_id is not None:
            candidates = candidates.filter(id__gt=after_id)

        return list(candidates.order_by("id").values_list("id", flat=True)[:batch_size])

    def _sanitize_releases(self, candidate_ids: list[UUID]) -> int:
        with transaction.atomic():
            releases: QuerySet[ErrorTrackingRelease] = ErrorTrackingRelease.objects.select_for_update().filter(
                id__in=candidate_ids
            )
            releases_to_update: list[ErrorTrackingRelease] = []
            for release in releases.only("id", "metadata"):
                sanitized_metadata = sanitize_release_metadata(release.metadata)
                if sanitized_metadata == release.metadata:
                    continue
                release.metadata = sanitized_metadata
                releases_to_update.append(release)

            if releases_to_update:
                ErrorTrackingRelease.objects.bulk_update(releases_to_update, ["metadata"])
            return len(releases_to_update)
